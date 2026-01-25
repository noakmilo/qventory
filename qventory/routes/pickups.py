import json
import secrets
from datetime import date, datetime, timedelta

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    make_response
)
from flask_login import login_required, current_user
from sqlalchemy import func
import requests

from ..extensions import db
from ..helpers import get_or_create_settings
from ..helpers.email_sender import send_pickup_scheduled_email, send_pickup_message_email
from ..models.notification import Notification
from ..models.pickup import PickupAppointment, PickupMessage
from ..models.setting import Setting
from ..models.user import User
from . import main_bp

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _load_json_list(raw):
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _parse_time_str(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def _build_slots_for_date(slot_date, settings, existing_map):
    if slot_date < date.today():
        return []
    mode = (settings.pickup_availability_mode or "weekly").strip().lower()
    specific_dates = set(_load_json_list(settings.pickup_specific_dates_json))
    weekly_days = set(_load_json_list(settings.pickup_weekly_days_json))

    day_key = slot_date.isoformat()
    if mode == "specific":
        if day_key not in specific_dates:
            return []
    else:
        weekday = WEEKDAYS[slot_date.weekday()]
        if weekday not in weekly_days:
            return []

    start_time = _parse_time_str(settings.pickup_start_time)
    end_time = _parse_time_str(settings.pickup_end_time)
    if not start_time or not end_time:
        return []

    break_blocks = _load_json_list(settings.pickup_breaks_json)
    break_start = _parse_time_str(break_blocks[0].get("start")) if break_blocks else None
    break_end = _parse_time_str(break_blocks[0].get("end")) if break_blocks else None

    duration = settings.pickup_slot_minutes or 15
    start_dt = datetime.combine(slot_date, start_time)
    end_dt = datetime.combine(slot_date, end_time)

    break_start_dt = datetime.combine(slot_date, break_start) if break_start else None
    break_end_dt = datetime.combine(slot_date, break_end) if break_end else None

    taken_times = existing_map.get(day_key, set())
    slots = []
    cursor = start_dt
    while cursor + timedelta(minutes=duration) <= end_dt:
        if break_start_dt and break_end_dt and break_start_dt <= cursor < break_end_dt:
            cursor += timedelta(minutes=duration)
            continue
        time_str = cursor.strftime("%H:%M")
        if time_str not in taken_times:
            slots.append(time_str)
        cursor += timedelta(minutes=duration)
    return slots


def _build_availability_map(settings, days_ahead, existing_map):
    today = date.today()
    availability = {}

    specific_dates = _load_json_list(settings.pickup_specific_dates_json)
    mode = (settings.pickup_availability_mode or "weekly").strip().lower()

    if mode == "specific":
        for raw in specific_dates:
            try:
                slot_date = date.fromisoformat(raw)
            except ValueError:
                continue
            if slot_date < today:
                continue
            slots = _build_slots_for_date(slot_date, settings, existing_map)
            if slots:
                availability[slot_date.isoformat()] = slots
        return availability

    for offset in range(days_ahead):
        slot_date = today + timedelta(days=offset)
        slots = _build_slots_for_date(slot_date, settings, existing_map)
        if slots:
            availability[slot_date.isoformat()] = slots
    return availability


def _resolve_public_user(slug):
    slug_norm = (slug or "").strip().lower()
    if not slug_norm:
        return None
    user = User.query.filter(func.lower(User.username) == slug_norm).first()
    if user:
        return user
    settings = Setting.query.filter_by(link_bio_slug=slug_norm).first()
    return settings.owner if settings else None


def _format_pickup_datetime(dt_value):
    return dt_value.strftime("%b %d, %Y"), dt_value.strftime("%I:%M %p").lstrip("0")


def _geocode_address(address):
    if not address:
        return None
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"format": "jsonv2", "limit": 1, "q": address},
            headers={"User-Agent": "Qventory Pickup Scheduler"},
            timeout=3
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        if not payload:
            return None
        return {
            "lat": float(payload[0].get("lat")),
            "lon": float(payload[0].get("lon"))
        }
    except Exception:
        return None


def _build_ics(appointment):
    start_str = appointment.scheduled_start.strftime("%Y%m%dT%H%M%S")
    end_str = appointment.scheduled_end.strftime("%Y%m%dT%H%M%S")
    description = f"Pickup with {appointment.seller.username}."
    if appointment.pickup_address:
        description += f" Address: {appointment.pickup_address}"

    ics_content = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Qventory//Pickup Scheduler//EN",
        "BEGIN:VEVENT",
        f"UID:{appointment.public_token}",
        f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{start_str}",
        f"DTEND:{end_str}",
        f"SUMMARY:Pickup with {appointment.seller.username}",
        f"DESCRIPTION:{description}",
        f"LOCATION:{appointment.pickup_address or ''}",
        "END:VEVENT",
        "END:VCALENDAR"
    ])
    return ics_content


@main_bp.route("/settings/pickup-scheduler", methods=["GET", "POST"])
@login_required
def settings_pickup_scheduler():
    settings = get_or_create_settings(current_user)

    if request.method == "POST":
        settings.pickup_scheduler_enabled = request.form.get("pickup_scheduler_enabled") == "on"
        settings.pickup_availability_mode = request.form.get("availability_mode") or "weekly"

        specific_dates_raw = (request.form.get("pickup_specific_dates") or "").strip()
        specific_dates = [d for d in specific_dates_raw.split(",") if d]
        settings.pickup_specific_dates_json = json.dumps(specific_dates)

        weekly_days = request.form.getlist("pickup_weekly_days")
        settings.pickup_weekly_days_json = json.dumps(weekly_days)

        settings.pickup_start_time = (request.form.get("pickup_start_time") or "").strip() or None
        settings.pickup_end_time = (request.form.get("pickup_end_time") or "").strip() or None

        break_start = (request.form.get("pickup_break_start") or "").strip()
        break_end = (request.form.get("pickup_break_end") or "").strip()
        breaks = []
        if break_start and break_end:
            breaks.append({"start": break_start, "end": break_end})
        settings.pickup_breaks_json = json.dumps(breaks)

        slot_minutes_raw = request.form.get("pickup_slot_minutes") or "15"
        try:
            settings.pickup_slot_minutes = int(slot_minutes_raw)
        except ValueError:
            settings.pickup_slot_minutes = 15

        settings.pickup_address = (request.form.get("pickup_address") or "").strip()
        settings.pickup_contact_email = (request.form.get("pickup_contact_email") or "").strip() or None
        settings.pickup_contact_phone = (request.form.get("pickup_contact_phone") or "").strip() or None
        settings.pickup_instructions = (request.form.get("pickup_instructions") or "").strip() or None

        if settings.pickup_scheduler_enabled:
            if not settings.pickup_start_time or not settings.pickup_end_time:
                flash("Please set a pickup start and end time.", "error")
                return redirect(url_for("main.settings_pickup_scheduler"))

            if settings.pickup_availability_mode == "specific" and not specific_dates:
                flash("Add at least one pickup date.", "error")
                return redirect(url_for("main.settings_pickup_scheduler"))

            if settings.pickup_availability_mode != "specific" and not weekly_days:
                flash("Select at least one pickup day.", "error")
                return redirect(url_for("main.settings_pickup_scheduler"))

            start_time = _parse_time_str(settings.pickup_start_time)
            end_time = _parse_time_str(settings.pickup_end_time)
            if not start_time or not end_time or start_time >= end_time:
                flash("Pickup start time must be before end time.", "error")
                return redirect(url_for("main.settings_pickup_scheduler"))

            if break_start and break_end:
                break_start_time = _parse_time_str(break_start)
                break_end_time = _parse_time_str(break_end)
                if not break_start_time or not break_end_time or break_start_time >= break_end_time:
                    flash("Break start time must be before break end time.", "error")
                    return redirect(url_for("main.settings_pickup_scheduler"))

        db.session.commit()
        flash("Pickup scheduler settings saved.", "ok")
        return redirect(url_for("main.settings_pickup_scheduler"))

    context = {
        "settings": settings,
        "specific_dates": _load_json_list(settings.pickup_specific_dates_json),
        "weekly_days": _load_json_list(settings.pickup_weekly_days_json),
        "breaks": _load_json_list(settings.pickup_breaks_json),
    }
    return render_template("settings_pickup_scheduler.html", **context)


@main_bp.route("/pickups/upcoming")
@login_required
def pickup_upcoming():
    Notification.query.filter_by(
        user_id=current_user.id,
        source="pickup",
        is_read=False
    ).update({"is_read": True, "read_at": datetime.utcnow()})
    db.session.commit()

    status_filter = (request.args.get("status") or "scheduled").strip().lower()
    valid_status = {"scheduled", "completed", "cancelled", "archived", "all"}
    if status_filter not in valid_status:
        status_filter = "scheduled"

    query = PickupAppointment.query.filter_by(seller_id=current_user.id)
    if status_filter != "all":
        query = query.filter_by(status=status_filter)

    pickups = query.order_by(PickupAppointment.scheduled_start.asc()).all()
    return render_template("pickup_upcoming.html", pickups=pickups, status_filter=status_filter)


@main_bp.route("/pickups/<int:pickup_id>")
@login_required
def pickup_detail(pickup_id):
    appointment = PickupAppointment.query.filter_by(
        id=pickup_id,
        seller_id=current_user.id
    ).first_or_404()
    messages = appointment.messages.order_by(PickupMessage.created_at.asc()).all()
    return render_template("pickup_detail.html", appointment=appointment, messages=messages)


@main_bp.route("/pickups/<int:pickup_id>/status", methods=["POST"])
@login_required
def pickup_update_status(pickup_id):
    appointment = PickupAppointment.query.filter_by(
        id=pickup_id,
        seller_id=current_user.id
    ).first_or_404()

    action = (request.form.get("action") or "").strip().lower()
    if action == "cancel":
        appointment.status = "cancelled"
    elif action == "complete":
        appointment.status = "completed"
    elif action == "archive":
        appointment.status = "archived"
    db.session.commit()
    return redirect(request.referrer or url_for("main.pickup_upcoming"))


@main_bp.route("/pickups/<int:pickup_id>/message", methods=["POST"])
@login_required
def pickup_send_message(pickup_id):
    appointment = PickupAppointment.query.filter_by(
        id=pickup_id,
        seller_id=current_user.id
    ).first_or_404()
    if appointment.status != "scheduled":
        flash("Messaging is closed for this pickup.", "error")
        return redirect(url_for("main.pickup_detail", pickup_id=pickup_id))
    message_body = (request.form.get("message") or "").strip()
    if not message_body:
        flash("Message cannot be empty.", "error")
        return redirect(url_for("main.pickup_detail", pickup_id=pickup_id))

    message = PickupMessage(
        pickup_id=appointment.id,
        sender_role="seller",
        sender_user_id=current_user.id,
        message=message_body
    )
    db.session.add(message)
    db.session.commit()

    reply_url = url_for("main.pickup_public_detail", token=appointment.public_token, _external=True)
    send_pickup_message_email(appointment.buyer_email, current_user.username, message_body, reply_url)
    flash("Message sent.", "ok")
    return redirect(url_for("main.pickup_detail", pickup_id=pickup_id))


@main_bp.route("/<slug>/pickup", methods=["GET", "POST"])
def pickup_public(slug):
    user = _resolve_public_user(slug)
    if not user:
        abort(404)

    settings = get_or_create_settings(user)
    availability_enabled = bool(settings.pickup_scheduler_enabled)

    start_date = date.today()
    end_date = start_date + timedelta(days=90)
    existing_appointments = PickupAppointment.query.filter(
        PickupAppointment.seller_id == user.id,
        PickupAppointment.status == "scheduled",
        PickupAppointment.scheduled_start >= datetime.combine(start_date, datetime.min.time()),
        PickupAppointment.scheduled_start <= datetime.combine(end_date, datetime.max.time())
    ).all()

    existing_map = {}
    for appointment in existing_appointments:
        day_key = appointment.scheduled_start.date().isoformat()
        existing_map.setdefault(day_key, set()).add(appointment.scheduled_start.strftime("%H:%M"))

    availability_map = _build_availability_map(settings, 45, existing_map)

    if request.method == "POST":
        if not availability_enabled:
            flash("Pickup scheduler is not active.", "error")
            return redirect(url_for("main.pickup_public", slug=slug))

        buyer_name = (request.form.get("buyer_name") or "").strip()
        buyer_email = (request.form.get("buyer_email") or "").strip().lower()
        buyer_phone = (request.form.get("buyer_phone") or "").strip()
        buyer_note = (request.form.get("buyer_note") or "").strip()
        selected_date = (request.form.get("pickup_date") or "").strip()
        selected_time = (request.form.get("pickup_time") or "").strip()

        if not buyer_name or not buyer_email:
            flash("Name and email are required.", "error")
            return redirect(url_for("main.pickup_public", slug=slug))

        if not selected_date or not selected_time:
            flash("Please select a pickup date and time.", "error")
            return redirect(url_for("main.pickup_public", slug=slug))

        try:
            slot_date = date.fromisoformat(selected_date)
        except ValueError:
            flash("Invalid pickup date.", "error")
            return redirect(url_for("main.pickup_public", slug=slug))

        slots = _build_slots_for_date(slot_date, settings, existing_map)
        if selected_time not in slots:
            flash("That pickup time is no longer available.", "error")
            return redirect(url_for("main.pickup_public", slug=slug))

        start_time = _parse_time_str(selected_time)
        if not start_time:
            flash("Invalid pickup time.", "error")
            return redirect(url_for("main.pickup_public", slug=slug))

        duration = settings.pickup_slot_minutes or 15
        start_dt = datetime.combine(slot_date, start_time)
        end_dt = start_dt + timedelta(minutes=duration)

        existing = PickupAppointment.query.filter_by(
            seller_id=user.id,
            status="scheduled",
            scheduled_start=start_dt
        ).first()
        if existing:
            flash("That pickup time is already booked.", "error")
            return redirect(url_for("main.pickup_public", slug=slug))

        appointment = PickupAppointment(
            seller_id=user.id,
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            buyer_phone=buyer_phone or None,
            buyer_note=buyer_note or None,
            scheduled_start=start_dt,
            scheduled_end=end_dt,
            duration_minutes=duration,
            status="scheduled",
            pickup_address=settings.pickup_address,
            seller_contact_email=settings.pickup_contact_email,
            seller_contact_phone=settings.pickup_contact_phone,
            seller_instructions=settings.pickup_instructions,
            public_token=secrets.token_urlsafe(24)
        )
        db.session.add(appointment)
        db.session.commit()

        Notification.create_notification(
            user_id=user.id,
            type="info",
            title="New pickup scheduled",
            message=f"{buyer_name} booked {selected_date} at {selected_time}.",
            link_url=url_for("main.pickup_detail", pickup_id=appointment.id),
            link_text="View pickup",
            source="pickup"
        )

        details_url = url_for("main.pickup_public_detail", token=appointment.public_token, _external=True)
        calendar_url = url_for("main.pickup_calendar", token=appointment.public_token, _external=True)
        pickup_date_str, pickup_time_str = _format_pickup_datetime(start_dt)
        send_pickup_scheduled_email(
            buyer_email,
            buyer_name,
            user.username,
            pickup_date_str,
            pickup_time_str,
            appointment.pickup_address,
            details_url,
            calendar_url
        )

        return redirect(url_for("main.pickup_public_detail", token=appointment.public_token))

    map_coords = _geocode_address(settings.pickup_address)
    return render_template(
        "pickup_public.html",
        seller=user,
        settings=settings,
        availability_enabled=availability_enabled,
        availability_map=availability_map,
        instructions=settings.pickup_instructions,
        map_coords=map_coords
    )


@main_bp.route("/pickup/<token>")
def pickup_public_detail(token):
    appointment = PickupAppointment.query.filter_by(public_token=token).first_or_404()
    messages = appointment.messages.order_by(PickupMessage.created_at.asc()).all()
    pickup_date, pickup_time = _format_pickup_datetime(appointment.scheduled_start)
    map_coords = _geocode_address(appointment.pickup_address)
    return render_template(
        "pickup_public_detail.html",
        appointment=appointment,
        messages=messages,
        pickup_date=pickup_date,
        pickup_time=pickup_time,
        map_coords=map_coords
    )


@main_bp.route("/pickup/<token>/message", methods=["POST"])
def pickup_public_message(token):
    appointment = PickupAppointment.query.filter_by(public_token=token).first_or_404()
    if appointment.status != "scheduled":
        flash("Messaging is closed for this pickup.", "error")
        return redirect(url_for("main.pickup_public_detail", token=token))
    message_body = (request.form.get("message") or "").strip()
    if not message_body:
        flash("Message cannot be empty.", "error")
        return redirect(url_for("main.pickup_public_detail", token=token))

    message = PickupMessage(
        pickup_id=appointment.id,
        sender_role="buyer",
        message=message_body
    )
    db.session.add(message)
    db.session.commit()

    Notification.create_notification(
        user_id=appointment.seller_id,
        type="info",
        title="New pickup message",
        message=f"Message from {appointment.buyer_name}.",
        link_url=url_for("main.pickup_detail", pickup_id=appointment.id),
        link_text="Reply",
        source="pickup"
    )

    reply_url = url_for("main.pickup_detail", pickup_id=appointment.id, _external=True)
    send_pickup_message_email(appointment.seller.email, appointment.buyer_name, message_body, reply_url)

    flash("Message sent.", "ok")
    return redirect(url_for("main.pickup_public_detail", token=token))


@main_bp.route("/pickup/<token>/calendar")
def pickup_calendar(token):
    appointment = PickupAppointment.query.filter_by(public_token=token).first_or_404()
    ics_content = _build_ics(appointment)
    response = make_response(ics_content)
    response.headers["Content-Type"] = "text/calendar; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=pickup.ics"
    return response
