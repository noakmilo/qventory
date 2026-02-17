import os
import sys
import requests
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from datetime import datetime, timedelta

from qventory.extensions import db
from qventory.models.ebay_feedback import EbayFeedback
from qventory.helpers.ebay_inventory import get_user_access_token, TRADING_API_URL, TRADING_COMPAT_LEVEL

_XML_NS = {"ebay": "urn:ebay:apis:eBLBaseComponents"}


def log_feedback(msg):
    print(f"[EBAY_FEEDBACK] {msg}", file=sys.stderr, flush=True)


def _parse_time(value):
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        return dt.replace(tzinfo=None)
    except Exception:
        return None


def _get_text(elem, path):
    node = elem.find(path, _XML_NS)
    return node.text.strip() if node is not None and node.text else None


def fetch_feedback_page(user_id, page=1, entries_per_page=200):
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {"success": False, "error": "No valid eBay access token"}

    app_id = os.environ.get("EBAY_CLIENT_ID")
    if not app_id:
        return {"success": False, "error": "Missing EBAY_CLIENT_ID"}

    xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<GetFeedbackRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <DetailLevel>ReturnAll</DetailLevel>
  <FeedbackType>FeedbackReceivedAsSeller</FeedbackType>
  <IncludeResponseDetails>true</IncludeResponseDetails>
  <Pagination>
    <EntriesPerPage>{entries_per_page}</EntriesPerPage>
    <PageNumber>{page}</PageNumber>
  </Pagination>
</GetFeedbackRequest>"""

    headers = {
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": TRADING_COMPAT_LEVEL,
        "X-EBAY-API-CALL-NAME": "GetFeedback",
        "X-EBAY-API-APP-NAME": app_id,
        "Content-Type": "text/xml",
    }

    try:
        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=30)
        if response.status_code != 200:
            return {"success": False, "error": f"HTTP {response.status_code}"}

        root = ET.fromstring(response.content)
        ack = root.find("ebay:Ack", _XML_NS)
        if ack is None or ack.text not in ["Success", "Warning"]:
            errors = root.findall(".//ebay:Errors", _XML_NS)
            error_msgs = []
            for error in errors:
                msg = error.find("ebay:LongMessage", _XML_NS)
                if msg is not None and msg.text:
                    error_msgs.append(msg.text)
            return {"success": False, "error": "; ".join(error_msgs) or "Unknown error"}

        details = root.findall(".//ebay:FeedbackDetail", _XML_NS)
        feedbacks = []
        for detail in details:
            feedback_id = _get_text(detail, "ebay:FeedbackID")
            comment_time = _parse_time(_get_text(detail, "ebay:CommentTime"))
            response_time = _parse_time(_get_text(detail, "ebay:ResponseTime"))
            response_text = _get_text(detail, "ebay:ResponseText")
            response_type = _get_text(detail, "ebay:ResponseType")
            response_details_elem = detail.find("ebay:ResponseDetails", _XML_NS)
            has_response_details = response_details_elem is not None

            if not response_text:
                response_text = _get_text(detail, "ebay:ResponseDetails/ebay:ResponseText")
            if not response_type:
                response_type = _get_text(detail, "ebay:ResponseDetails/ebay:ResponseType")
            if not response_time:
                response_time = _parse_time(_get_text(detail, "ebay:ResponseDetails/ebay:ResponseTime"))

            feedbacks.append({
                "feedback_id": feedback_id,
                "comment_type": _get_text(detail, "ebay:CommentType"),
                "comment_text": _get_text(detail, "ebay:CommentText"),
                "comment_time": comment_time,
                "commenting_user": _get_text(detail, "ebay:CommentingUser"),
                "role": _get_text(detail, "ebay:Role"),
                "item_id": _get_text(detail, "ebay:ItemID"),
                "transaction_id": _get_text(detail, "ebay:TransactionID"),
                "order_line_item_id": _get_text(detail, "ebay:OrderLineItemID"),
                "item_title": _get_text(detail, "ebay:ItemTitle"),
                "response_text": response_text,
                "response_type": response_type,
                "response_time": response_time,
                "has_response_details": has_response_details,
                "responded": bool(response_text) or bool(response_time) or has_response_details,
            })

        total_pages = None
        pagination = root.find("ebay:PaginationResult", _XML_NS)
        if pagination is not None:
            total_pages = _get_text(pagination, "ebay:TotalNumberOfPages")
            try:
                total_pages = int(total_pages)
            except Exception:
                total_pages = None

        has_more = total_pages is None or page < total_pages
        return {"success": True, "feedbacks": feedbacks, "has_more": has_more}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def sync_ebay_feedback_for_user(user_id, days_back=1, max_pages=10, entries_per_page=200):
    since = None
    if days_back is not None:
        since = datetime.utcnow() - timedelta(days=days_back)

    created = 0
    updated = 0
    total = 0

    for page in range(1, max_pages + 1):
        result = fetch_feedback_page(user_id, page=page, entries_per_page=entries_per_page)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "Unknown error")}

        feedbacks = result.get("feedbacks", [])
        if not feedbacks:
            break

        stop_early = False
        for feedback in feedbacks:
            comment_time = feedback.get("comment_time")
            if since and comment_time and comment_time < since:
                stop_early = True
                continue

            if not feedback.get("feedback_id"):
                continue

            existing = EbayFeedback.query.filter_by(
                user_id=user_id,
                feedback_id=feedback["feedback_id"]
            ).first()

            if existing:
                existing.comment_type = feedback.get("comment_type")
                existing.comment_text = feedback.get("comment_text")
                existing.comment_time = comment_time
                existing.commenting_user = feedback.get("commenting_user")
                existing.role = feedback.get("role")
                existing.item_id = feedback.get("item_id")
                existing.transaction_id = feedback.get("transaction_id")
                existing.order_line_item_id = feedback.get("order_line_item_id")
                existing.item_title = feedback.get("item_title")
                existing.response_text = feedback.get("response_text")
                existing.response_type = feedback.get("response_type")
                existing.response_time = feedback.get("response_time")
                existing.responded = (
                    bool(feedback.get("response_text"))
                    or bool(feedback.get("response_time"))
                    or bool(feedback.get("has_response_details"))
                )
                if existing.responded and not existing.response_source:
                    existing.response_source = "ebay"
                updated += 1
            else:
                db.session.add(EbayFeedback(
                    user_id=user_id,
                    feedback_id=feedback.get("feedback_id"),
                    comment_type=feedback.get("comment_type"),
                    comment_text=feedback.get("comment_text"),
                    comment_time=comment_time,
                    commenting_user=feedback.get("commenting_user"),
                    role=feedback.get("role"),
                    item_id=feedback.get("item_id"),
                    transaction_id=feedback.get("transaction_id"),
                    order_line_item_id=feedback.get("order_line_item_id"),
                    item_title=feedback.get("item_title"),
                    response_text=feedback.get("response_text"),
                    response_type=feedback.get("response_type"),
                    response_time=feedback.get("response_time"),
                    responded=(
                        bool(feedback.get("response_text"))
                        or bool(feedback.get("response_time"))
                        or bool(feedback.get("has_response_details"))
                    ),
                    response_source="ebay" if (
                        feedback.get("response_text")
                        or feedback.get("response_time")
                        or feedback.get("has_response_details")
                    ) else None
                ))
                created += 1
            total += 1

        db.session.commit()

        if stop_early or not result.get("has_more"):
            break

    return {"success": True, "created": created, "updated": updated, "total": total}


def respond_to_feedback(user_id, feedback: EbayFeedback, response_text: str, response_type: str = "Reply"):
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {"success": False, "error": "No valid eBay access token"}

    app_id = os.environ.get("EBAY_CLIENT_ID")
    if not app_id:
        return {"success": False, "error": "Missing EBAY_CLIENT_ID"}

    response_text = (response_text or "").strip()
    if not response_text:
        return {"success": False, "error": "Response text is required"}

    item_id_xml = f"<ItemID>{feedback.item_id}</ItemID>" if feedback.item_id else ""
    transaction_id_xml = f"<TransactionID>{feedback.transaction_id}</TransactionID>" if feedback.transaction_id else ""
    order_line_item_id_xml = f"<OrderLineItemID>{feedback.order_line_item_id}</OrderLineItemID>" if feedback.order_line_item_id else ""
    target_user_xml = f"<TargetUserID>{feedback.commenting_user}</TargetUserID>" if feedback.commenting_user else ""

    xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<RespondToFeedbackRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <FeedbackID>{feedback.feedback_id}</FeedbackID>
  {target_user_xml}
  {item_id_xml}
  {transaction_id_xml}
  {order_line_item_id_xml}
  <ResponseType>{response_type}</ResponseType>
  <ResponseText>{escape(response_text)}</ResponseText>
</RespondToFeedbackRequest>"""

    headers = {
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": TRADING_COMPAT_LEVEL,
        "X-EBAY-API-CALL-NAME": "RespondToFeedback",
        "X-EBAY-API-APP-NAME": app_id,
        "Content-Type": "text/xml",
    }

    try:
        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=30)
        if response.status_code != 200:
            return {"success": False, "error": f"HTTP {response.status_code}"}

        root = ET.fromstring(response.content)
        ack = root.find("ebay:Ack", _XML_NS)
        if ack is not None and ack.text in ["Success", "Warning"]:
            return {"success": True}

        errors = root.findall(".//ebay:Errors", _XML_NS)
        error_msgs = []
        for error in errors:
            msg = error.find("ebay:LongMessage", _XML_NS)
            if msg is not None and msg.text:
                error_msgs.append(msg.text)
        return {"success": False, "error": "; ".join(error_msgs) or "Unknown error"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
