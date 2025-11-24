from functools import wraps
from flask import Flask, session, redirect, url_for, request
from flask_session import Session
from authlib.integrations.flask_client import OAuth
from dash import html, Input, Output
from db import get_person_id_for_user
from dotenv import load_dotenv
import os

# ---------------------------------------------------------
# Flask + OAuth setup
# ---------------------------------------------------------

load_dotenv()
server = Flask(__name__)
server.secret_key = os.environ.get("SECRET_KEY")
server.config["SESSION_TYPE"] = "filesystem"
server.config["SESSION_PERMANENT"] = False
Session(server)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8050/auth/callback")

oauth = OAuth(server)
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    access_token_url="https://oauth2.googleapis.com/token",
    access_token_params=None,
    authorize_url="https://accounts.google.com/o/oauth2/auth",
    authorize_params=None,
    api_base_url="https://www.googleapis.com/oauth2/v1/",
    userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# ---------------------------------------------------------
# Auth routes and helpers
# ---------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

@server.before_request
def simulate_local_login():
    """Automatically log in as a fake user for local development."""
    in_docker = os.getcwd() == "/app"
    debug_env = os.environ.get("DEBUG", None)
    if not in_docker and (debug_env is None or debug_env.lower() in ("1", "true", "yes", "on")):
        if "user" not in session:
            session["user"] = {
                "sub": "localdev",
                "email": "localhost@example.com",
                "name": "Local Developer",
                "picture": None,
            }

@server.route("/login")
def login():
    redirect_uri = OAUTH_REDIRECT_URI
    return oauth.google.authorize_redirect(redirect_uri)


@server.route("/auth/callback")
def auth_callback():
    token = oauth.google.authorize_access_token()
    userinfo = oauth.google.get("userinfo").json()
    if not userinfo.get("email").endswith("@idems.international"):
        return redirect("unauthorized")
    session["user"] = {
        "email": userinfo.get("email"),
        "name": userinfo.get("name"),
        "picture": userinfo.get("picture"),
    }
    next_url = request.args.get("next") or "/"
    return redirect(next_url)


@server.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


def register_auth_callbacks(app):
    @app.callback(Output("login-area", "children"), Input("table-selector", "value"))
    def show_login_area(_):
        user = session.get("user")
        if user:
            return html.Div([
                html.Img(src=user["picture"], style={"height": "40px", "marginRight": "10px"}),
                html.Span(f"Logged in as {user['name']} ({user['email']})"),
                html.Br(),
                html.A("Logout", href="/logout")
            ])
        else:
            return html.Div(html.A("Login with Google", href="/login"))


    @app.callback(
        Output("current-person-id", "data"),
        Input("intermediary-loaded", "data"),  # or whatever triggers your load
    )
    def populate_person_id(_):
        person_id = get_person_id_for_user(session["user"])
        return person_id