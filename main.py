import asyncio

from quart import Quart
from quart.templating import render_template

from quart_tryton import Tryton, tryton_transaction

app = Quart(__name__)
app.jinja_env.auto_reload = True
app.config["TRYTON_DATABASE"] = "test"
app.config["TEMPLATES_AUTO_RELOAD"] = True

tryton = Tryton(app, configure_jinja=True)

User = tryton.pool.get("res.user")


@app.route("/login-test", methods=["GET", "POST"])
@tryton_transaction()
async def login_test():
    username = "admin"  # data.get("username")
    password = "1234"  # data.get("password")
    (user,) = User.search([("login", "=", username)])

    stored_password_hash = await asyncio.to_thread(getattr, user, "password")
    is_valid = await asyncio.to_thread(
        User.check_password, stored_password_hash, password
    )

    print(is_valid)
    return f"User: {is_valid}"


@app.route("/")
async def home():
    return await render_template("home.html", hello="world")


@app.route("/hello")
@tryton_transaction()
async def hello():
    (user,) = User.search([("login", "=", "admin")])
    return f"{user.name}, Hello World!"


app.run(debug=True, host="0.0.0.0")
