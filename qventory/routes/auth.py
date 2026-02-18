from flask import render_template, request, redirect, url_for, flash, session
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
        remember = request.form.get("remember_me") == "on"

        # define 'user' SIEMPRE dentro del POST (no en GET)
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            # Check if email is verified
            if not user.email_verified:
                flash("Please verify your email before signing in. Check your inbox for the verification code.", "error")
                return redirect(url_for("auth.verify_email", email=email))

            # Login user with remember me functionality
            login_user(user, remember=remember)

            # Update last login timestamp (after login_user)
            user.last_login = datetime.utcnow()
            db.session.commit()

            flash("Welcome back.", "ok")
            return redirect(_safe_next())
        else:
            flash("Invalid email or password. Please try again.", "error")

    # GET o POST con error de credenciales
    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        pending_plan = (request.form.get("plan") or "").strip().lower()
        if pending_plan in {"premium", "plus", "pro"}:
            session["pending_plan"] = pending_plan
        elif pending_plan == "free":
            session.pop("pending_plan", None)

        email = (request.form.get("email") or "").strip().lower()
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        # email validation
        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            flash("Please enter a valid email address.", "error")
            return render_template("register.html", email=email, username=username, pending_plan=pending_plan)

        # Check if email already exists
        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists. Please sign in or use a different email.", "error")
            return render_template("register.html", email=email, username=username, pending_plan=pending_plan)

        # username validation
        if not re.fullmatch(r"[a-z0-9_-]{3,32}", username):
            flash("Username must be 3–32 chars, lowercase letters, numbers, _ or -.", "error")
            return render_template("register.html", email=email, username=username, pending_plan=pending_plan)
        if User.query.filter_by(username=username).first():
            flash("This username is taken.", "error")
            return render_template("register.html", email=email, username=username, pending_plan=pending_plan)

        # passwords
        if not password or not password2:
            flash("All fields are required.", "error")
            return render_template("register.html", email=email, username=username, pending_plan=pending_plan)
        if password != password2:
            flash("Passwords do not match.", "error")
            return render_template("register.html", email=email, username=username, pending_plan=pending_plan)
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html", email=email, username=username, pending_plan=pending_plan)

        # create user + settings inicial
        user = User(email=email, username=username)
        user.set_password(password)
        user.email_verified = False  # User must verify email
        # attach referral metadata if present
        ref_source = session.get("ref_source")
        if ref_source:
            user.ref_source = ref_source
            user.ref_medium = session.get("ref_medium")
            user.ref_campaign = session.get("ref_campaign")
            user.ref_content = session.get("ref_content")
            user.ref_term = session.get("ref_term")
            user.ref_landing_path = session.get("ref_landing_path")
            try:
                user.ref_first_touch_at = datetime.fromisoformat(session.get("ref_first_touch_at"))
            except Exception:
                user.ref_first_touch_at = datetime.utcnow()
        db.session.add(user)
        db.session.commit()

        # settings vacío por usuario
        from ..helpers import get_or_create_settings
        get_or_create_settings(user)

        # Create and send verification code
        from ..models.email_verification import EmailVerification
        from ..helpers.email_sender import send_verification_email

        verification = EmailVerification.create_verification(
            user_id=user.id,
            email=email,
            purpose='registration'
        )

        success, error = send_verification_email(email, verification.code, username)

        if success:
            flash("Account created! Please check your email for a verification code.", "ok")
            return redirect(url_for("auth.verify_email", email=email))
        else:
            # Email failed to send, but account was created
            flash(f"Account created, but we couldn't send the verification email: {error}. You can request a new code.", "error")
            return redirect(url_for("auth.verify_email", email=email))

    pending_plan = (request.args.get("plan") or "").strip().lower()
    if pending_plan in {"premium", "plus", "pro", "free"}:
        session["pending_plan"] = pending_plan
    return render_template("register.html", pending_plan=pending_plan)


@auth_bp.route("/verify-email", methods=["GET", "POST"])
def verify_email():
    """Email verification page where user enters 6-digit code"""
    email = request.args.get("email") or request.form.get("email")

    if not email:
        flash("Email address is required.", "error")
        return redirect(url_for("auth.login"))

    # If user is already logged in and verified, redirect to dashboard
    if current_user.is_authenticated and current_user.email_verified:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        code = (request.form.get("code") or "").strip()

        if not code or len(code) != 6 or not code.isdigit():
            flash("Please enter a valid 6-digit code.", "error")
            show_checkout_redirect = session.get("pending_plan") in {"premium", "plus", "pro"}
            return render_template("verify_email.html", email=email, show_checkout_redirect=show_checkout_redirect)

        # Verify the code
        from ..models.email_verification import EmailVerification

        success, message, verification = EmailVerification.verify_code(
            email=email,
            code=code,
            purpose='registration'
        )

        if success:
            # Mark user as verified
            user = User.query.filter_by(email=email).first()
            if user:
                user.email_verified = True
                db.session.commit()
                try:
                    from ..helpers.email_sender import send_welcome_verified_email
                    send_welcome_verified_email(user.email, user.username)
                except Exception:
                    pass

                # Auto-login the user
                login_user(user)
                pending_plan = session.pop("pending_plan", None)
                if pending_plan in {"premium", "plus", "pro"}:
                    flash("Email verified successfully! Redirecting you to checkout.", "ok")
                    return redirect(url_for("main.stripe_checkout_start", plan_name=pending_plan))

                flash("Email verified successfully! Welcome to Qventory.", "ok")
                return redirect(url_for("main.dashboard"))
            else:
                flash("User not found.", "error")
        else:
            # Increment failed attempts
            if verification:
                verification.increment_attempts()
                db.session.commit()

            flash(message, "error")

    show_checkout_redirect = session.get("pending_plan") in {"premium", "plus", "pro"}
    return render_template("verify_email.html", email=email, show_checkout_redirect=show_checkout_redirect)


@auth_bp.route("/resend-verification", methods=["POST"])
def resend_verification():
    """Resend verification code"""
    email = (request.form.get("email") or "").strip().lower()

    if not email:
        flash("Email address is required.", "error")
        return redirect(url_for("auth.login"))

    # Find user
    user = User.query.filter_by(email=email).first()
    if not user:
        # Don't reveal if email exists or not (security)
        flash("If the email exists, a new verification code has been sent.", "ok")
        return redirect(url_for("auth.verify_email", email=email))

    if user.email_verified:
        flash("Your email is already verified. You can sign in.", "ok")
        return redirect(url_for("auth.login"))

    # Get existing verification or create new one
    from ..models.email_verification import EmailVerification

    existing = EmailVerification.query.filter_by(
        user_id=user.id,
        purpose='registration',
        used_at=None
    ).order_by(EmailVerification.created_at.desc()).first()

    if existing:
        # Check if we can resend
        can_resend, error_message = existing.can_resend()
        if not can_resend:
            flash(error_message, "error")
            return redirect(url_for("auth.verify_email", email=email))

        # Resend the code
        existing.resend()
        db.session.commit()
        verification = existing
    else:
        # Create new verification
        verification = EmailVerification.create_verification(
            user_id=user.id,
            email=email,
            purpose='registration'
        )

    # Send email
    from ..helpers.email_sender import send_verification_email
    success, error = send_verification_email(email, verification.code, user.username)

    if success:
        flash("A new verification code has been sent to your email.", "ok")
    else:
        flash(f"Failed to send email: {error}", "error")

    return redirect(url_for("auth.verify_email", email=email))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Forgot password - send reset code to email"""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()

        # Find user
        user = User.query.filter_by(email=email).first()

        # Always show success message (don't reveal if email exists - security)
        if not user:
            flash("If an account exists with this email, a password reset code has been sent.", "ok")
            return redirect(url_for("auth.reset_password", email=email))

        # Create verification code for password reset
        from ..models.email_verification import EmailVerification
        from ..helpers.email_sender import send_password_reset_email

        verification = EmailVerification.create_verification(
            user_id=user.id,
            email=email,
            purpose='password_reset'
        )

        # Send reset email
        success, error = send_password_reset_email(email, verification.code, user.username)

        if success:
            flash("A password reset code has been sent to your email.", "ok")
        else:
            flash(f"Failed to send email: {error}", "error")

        return redirect(url_for("auth.reset_password", email=email))

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    """Reset password using verification code"""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    email = request.args.get("email") or request.form.get("email")

    if not email:
        flash("Email address is required.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        # Validate code
        if not code or len(code) != 6 or not code.isdigit():
            flash("Please enter a valid 6-digit code.", "error")
            return render_template("reset_password.html", email=email)

        # Validate passwords
        if not new_password or not confirm_password:
            flash("All fields are required.", "error")
            return render_template("reset_password.html", email=email)

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html", email=email)

        if len(new_password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("reset_password.html", email=email)

        # Verify the code
        from ..models.email_verification import EmailVerification

        success, message, verification = EmailVerification.verify_code(
            email=email,
            code=code,
            purpose='password_reset'
        )

        if success:
            # Update password
            user = User.query.filter_by(email=email).first()
            if user:
                user.set_password(new_password)
                db.session.commit()

                flash("Password reset successfully! You can now sign in with your new password.", "ok")
                return redirect(url_for("auth.login"))
            else:
                flash("User not found.", "error")
        else:
            # Increment failed attempts
            if verification:
                verification.increment_attempts()
                db.session.commit()

            flash(message, "error")

    return render_template("reset_password.html", email=email)


@auth_bp.route("/resend-reset-code", methods=["POST"])
def resend_reset_code():
    """Resend password reset code"""
    email = (request.form.get("email") or "").strip().lower()

    if not email:
        flash("Email address is required.", "error")
        return redirect(url_for("auth.forgot_password"))

    # Find user
    user = User.query.filter_by(email=email).first()
    if not user:
        # Don't reveal if email exists or not (security)
        flash("If the email exists, a new reset code has been sent.", "ok")
        return redirect(url_for("auth.reset_password", email=email))

    # Get existing verification or create new one
    from ..models.email_verification import EmailVerification

    existing = EmailVerification.query.filter_by(
        user_id=user.id,
        purpose='password_reset',
        used_at=None
    ).order_by(EmailVerification.created_at.desc()).first()

    if existing:
        # Check if we can resend
        can_resend, error_message = existing.can_resend()
        if not can_resend:
            flash(error_message, "error")
            return redirect(url_for("auth.reset_password", email=email))

        # Resend the code
        existing.resend()
        db.session.commit()
        verification = existing
    else:
        # Create new verification
        verification = EmailVerification.create_verification(
            user_id=user.id,
            email=email,
            purpose='password_reset'
        )

    # Send email
    from ..helpers.email_sender import send_password_reset_email
    success, error = send_password_reset_email(email, verification.code, user.username)

    if success:
        flash("A new reset code has been sent to your email.", "ok")
    else:
        flash(f"Failed to send email: {error}", "error")

    return redirect(url_for("auth.reset_password", email=email))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "ok")
    return redirect(url_for("auth.login"))
