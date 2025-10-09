from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from email_validator import validate_email, EmailNotValidError
from datetime import datetime

from ..extensions import db
from ..models.user import User
from . import auth_bp
import re


def _safe_next(default_endpoint="main.dashboard"):
    """
    Lee ?next= y solo permite rutas internas que comienzan con "/".
    Si no hay next válido, devuelve url_for(default_endpoint).
    """
    dest = request.args.get("next")
    if dest and dest.startswith("/"):
        return dest
    return url_for(default_endpoint)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # si ya está autenticado, llévalo al destino (o dashboard)
    if current_user.is_authenticated:
        return redirect(_safe_next())

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        # define 'user' SIEMPRE dentro del POST (no en GET)
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)

            # Update last login timestamp (after login_user)
            user.last_login = datetime.utcnow()
            db.session.commit()

            flash("Welcome back.", "ok")
            return redirect(_safe_next())
        else:
            flash("Invalid credentials.", "error")

    # GET o POST con error de credenciales
    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        # email
        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            flash("Please enter a valid email address.", "error")
            return render_template("register.html", email=email, username=username)

        # username
        if not re.fullmatch(r"[a-z0-9_-]{3,32}", username):
            flash("Username must be 3–32 chars, lowercase letters, numbers, _ or -.", "error")
            return render_template("register.html", email=email, username=username)
        if User.query.filter_by(username=username).first():
            flash("This username is taken.", "error")
            return render_template("register.html", email=email, username=username)

        # passwords
        if not password or not password2:
            flash("All fields are required.", "error")
            return render_template("register.html", email=email, username=username)
        if password != password2:
            flash("Passwords do not match.", "error")
            return render_template("register.html", email=email, username=username)
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html", email=email, username=username)

        # create user + settings inicial
        user = User(email=email, username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # settings vacío por usuario
        from ..helpers import get_or_create_settings
        get_or_create_settings(user)

        flash("Account created. Please sign in.", "ok")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "ok")
    return redirect(url_for("auth.login"))
