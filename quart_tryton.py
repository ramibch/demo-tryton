# Original code: https://pypi.org/project/flask-tryton/
# Adapted for quart

import time
from functools import wraps

from quart import current_app, request
from trytond.config import config
from trytond.exceptions import ConcurrencyException, UserError, UserWarning
from werkzeug.exceptions import BadRequest
from werkzeug.routing import BaseConverter


class Tryton:
    def __init__(self, app=None, configure_jinja=False):
        self.context_callback = None
        self.database_retry = None
        self._configure_jinja = configure_jinja
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        database = app.config.setdefault("TRYTON_DATABASE", None)
        user = app.config.setdefault("TRYTON_USER", 0)
        configfile = app.config.setdefault("TRYTON_CONFIG", None)

        config.update_etc(configfile)

        from trytond.pool import Pool
        from trytond.transaction import Transaction

        Pool.stop = classmethod(lambda cls, database_name: None)  # Freeze pool

        self.database_retry = config.getint("database", "retry")
        self.pool = Pool(database)
        with Transaction().start(database, user, readonly=True):
            self.pool.init()

        if not hasattr(app, "extensions"):
            app.extensions = {}
        app.extensions["Tryton"] = self
        app.url_map.converters["record"] = RecordConverter
        app.url_map.converters["records"] = RecordsConverter

    def default_context(self, callback):
        self.context_callback = callback
        return callback

    async def _readonly(self):
        return not (request and request.method in ("PUT", "POST", "DELETE", "PATCH"))

    @staticmethod
    def transaction(readonly=None, user=None, context=None):
        """Decorator to run inside a Tryton transaction."""

        from trytond import backend
        from trytond.transaction import Transaction

        try:
            from trytond.transaction import TransactionError
        except ImportError:

            class TransactionError(Exception):
                pass

        try:
            DatabaseOperationalError = backend.DatabaseOperationalError
        except AttributeError:
            DatabaseOperationalError = backend.get("DatabaseOperationalError")

        def get_value(value):
            return value() if callable(value) else value

        def extract_data(obj):
            """Convert Tryton ORM objects to dictionaries to avoid issues after transaction closes."""
            if isinstance(obj, list):
                return [extract_data(item) for item in obj]
            elif hasattr(obj, "__dict__"):  # Check if it is a Tryton model instance
                return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
            return obj

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                tryton = current_app.extensions["Tryton"]
                database = current_app.config["TRYTON_DATABASE"]
                transaction_user = get_value(
                    user or int(current_app.config["TRYTON_USER"])
                )
                is_readonly = get_value(
                    readonly if readonly is not None else tryton._readonly
                )

                transaction_context = {}
                if tryton.context_callback or context:
                    with Transaction().start(database, transaction_user, readonly=True):
                        if tryton.context_callback:
                            transaction_context = tryton.context_callback()
                        transaction_context.update(get_value(context) or {})

                transaction_context.setdefault("_request", {}).update(
                    {
                        "remote_addr": request.remote_addr,
                        "http_host": request.host,
                        "scheme": request.scheme,
                        "is_secure": request.is_secure,
                    }
                    if request
                    else {}
                )

                retry = tryton.database_retry
                count = 0
                transaction_extras = {}

                while True:
                    if count:
                        time.sleep(0.02 * count)

                    with Transaction().start(
                        database,
                        transaction_user,
                        readonly=is_readonly,
                        context=transaction_context,
                        **transaction_extras,
                    ) as transaction:
                        try:
                            result = await func(*args, **kwargs)

                            # Convert Tryton ORM objects to plain dictionaries before returning
                            if isinstance(result, tuple):
                                return tuple(extract_data(r) for r in result)
                            return extract_data(result)

                        except TransactionError as e:
                            transaction.rollback()
                            transaction.tasks.clear()
                            e.fix(transaction_extras)
                            continue
                        except DatabaseOperationalError:
                            if count < retry and not transaction.readonly:
                                transaction.rollback()
                                transaction.tasks.clear()
                                count += 1
                                continue
                            raise
                        except (UserError, UserWarning, ConcurrencyException) as e:
                            raise BadRequest(e.message)

                    from trytond.worker import run_task

                    while transaction.tasks:
                        task_id = transaction.tasks.pop()
                        run_task(tryton.pool, task_id)

            return wrapper

        return decorator


tryton_transaction = Tryton.transaction


class _BaseProxy:
    pass


class _RecordsProxy(_BaseProxy):
    def __init__(self, model, ids):
        self.model = model
        self.ids = list(ids)

    def __iter__(self):
        return iter(self.ids)

    def __call__(self):
        tryton = current_app.extensions["Tryton"]
        Model = tryton.pool.get(self.model)
        return Model.browse(self.ids)


class _RecordProxy(_RecordsProxy):
    def __init__(self, model, id):
        super().__init__(model, [id])

    def __int__(self):
        return self.ids[0]

    def __call__(self):
        return super().__call__()[0]


class RecordConverter(BaseConverter):
    regex = r"\d+"

    def __init__(self, map, model):
        super().__init__(map)
        self.model = model

    def to_python(self, value):
        return _RecordProxy(self.model, int(value))

    def to_url(self, value):
        return str(int(value))


class RecordsConverter(BaseConverter):
    regex = r"\d+(,\d+)*"

    def __init__(self, map, model):
        super().__init__(map)
        self.model = model

    def to_python(self, value):
        return _RecordsProxy(self.model, map(int, value.split(",")))

    def to_url(self, value):
        return ",".join(map(str, map(int, value)))
