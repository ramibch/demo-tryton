from quart import Quart, request
from quart.templating import render_template

from erp import tryton_login

app = Quart(__name__)


@app.route("/")
async def home():
    return await render_template("home.html", hello="world")


@app.route("/login", methods=["POST"])
async def login():
    form = await request.form
    username = form.get("username")
    password = form.get("password")

    user_id = await tryton_login(username, password)

    return await render_template("home.html", hello="world")


if __name__ == "__main__":
    app.jinja_env.auto_reload = True
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.run(debug=True, host="0.0.0.0")
