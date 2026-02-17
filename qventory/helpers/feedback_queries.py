from qventory.models.ebay_feedback import EbayFeedback


def count_unread_feedback(session, user_id, since_dt):
    if not since_dt:
        return 0
    return session.query(EbayFeedback).filter(
        EbayFeedback.user_id == user_id,
        EbayFeedback.comment_time.isnot(None),
        EbayFeedback.comment_time > since_dt
    ).count()
