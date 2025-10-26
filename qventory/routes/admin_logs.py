"""
Admin Logs Console
Real-time monitoring of Celery tasks and system events
Optimized for low resource usage
"""
from flask import Blueprint, render_template, jsonify, request, Response
from qventory.extensions import db
from qventory.models.user import User
from qventory.models.import_job import ImportJob
from datetime import datetime, timedelta
from sqlalchemy import func, desc
import json

admin_logs_bp = Blueprint('admin_logs', __name__, url_prefix='/admin/logs')

# Import admin auth helpers from main routes
from qventory.routes.main import check_admin_auth, require_admin


@admin_logs_bp.route('/', methods=['GET'])
@require_admin
def logs_console():
    """
    Logs console - Admin only
    Shows Celery tasks, import jobs, and system events
    """
    return render_template('admin_logs_console.html')


@admin_logs_bp.route('/api/celery-tasks', methods=['GET'])
@require_admin
def get_celery_tasks():
    """
    Get recent Celery task executions via ImportJob model
    """
    limit = int(request.args.get('limit', 50))
    status = request.args.get('status')  # processing, completed, failed

    # Build query
    query = ImportJob.query

    if status:
        query = query.filter_by(status=status)

    # Get jobs with user info
    jobs = db.session.query(
        ImportJob,
        User.username,
        User.email
    ).join(
        User, ImportJob.user_id == User.id
    ).order_by(
        desc(ImportJob.started_at)
    ).limit(limit).all()

    return jsonify({
        'tasks': [
            {
                'id': job.id,
                'task_id': job.celery_task_id,
                'user_id': job.user_id,
                'username': username,
                'email': email,
                'import_mode': job.import_mode,
                'listing_status': job.listing_status,
                'status': job.status,
                'total_items': job.total_items,
                'items_imported': job.items_imported,
                'items_updated': job.items_updated,
                'items_failed': job.items_failed,
                'started_at': job.started_at.isoformat() if job.started_at else None,
                'completed_at': job.completed_at.isoformat() if job.completed_at else None,
                'error_message': job.error_message,
                'duration_seconds': (
                    (job.completed_at - job.started_at).total_seconds()
                    if job.completed_at and job.started_at else None
                )
            }
            for job, username, email in jobs
        ],
        'total': len(jobs)
    }), 200


@admin_logs_bp.route('/api/stats', methods=['GET'])
@require_admin
def get_system_stats():
    """
    Get overall system statistics
    Optimized to minimize database queries
    """

    # Task stats by status (single query)
    task_stats = db.session.query(
        ImportJob.status,
        func.count(ImportJob.id)
    ).group_by(ImportJob.status).all()

    # Recent activity (last 24 hours)
    last_24h = datetime.utcnow() - timedelta(hours=24)
    tasks_last_24h = ImportJob.query.filter(
        ImportJob.started_at >= last_24h
    ).count()

    # Failed tasks in last 24h
    failed_last_24h = ImportJob.query.filter(
        ImportJob.started_at >= last_24h,
        ImportJob.status == 'failed'
    ).count()

    # Currently processing tasks
    processing_now = ImportJob.query.filter_by(status='processing').count()

    # Average task duration (completed tasks only, last 100)
    completed_jobs = ImportJob.query.filter_by(
        status='completed'
    ).order_by(
        desc(ImportJob.completed_at)
    ).limit(100).all()

    avg_duration = None
    if completed_jobs:
        durations = [
            (job.completed_at - job.started_at).total_seconds()
            for job in completed_jobs
            if job.completed_at and job.started_at
        ]
        if durations:
            avg_duration = sum(durations) / len(durations)

    # Top users by task count (last 7 days)
    last_7d = datetime.utcnow() - timedelta(days=7)
    top_users = db.session.query(
        User.username,
        func.count(ImportJob.id).label('task_count')
    ).join(
        ImportJob, User.id == ImportJob.user_id
    ).filter(
        ImportJob.started_at >= last_7d
    ).group_by(
        User.username
    ).order_by(
        desc('task_count')
    ).limit(5).all()

    return jsonify({
        'tasks': {
            'by_status': dict(task_stats),
            'total': sum(count for _, count in task_stats),
            'last_24h': tasks_last_24h,
            'failed_last_24h': failed_last_24h,
            'processing_now': processing_now
        },
        'performance': {
            'avg_duration_seconds': round(avg_duration, 2) if avg_duration else None
        },
        'top_users': [
            {'username': username, 'task_count': count}
            for username, count in top_users
        ],
        'timestamp': datetime.utcnow().isoformat()
    }), 200


@admin_logs_bp.route('/api/errors', methods=['GET'])
@require_admin
def get_recent_errors():
    """
    Get recent failed tasks with error details
    """
    limit = int(request.args.get('limit', 30))

    # Get failed jobs with user info
    errors = db.session.query(
        ImportJob,
        User.username,
        User.email
    ).join(
        User, ImportJob.user_id == User.id
    ).filter(
        ImportJob.status == 'failed'
    ).order_by(
        desc(ImportJob.started_at)
    ).limit(limit).all()

    return jsonify({
        'errors': [
            {
                'id': job.id,
                'task_id': job.celery_task_id,
                'user_id': job.user_id,
                'username': username,
                'email': email,
                'import_mode': job.import_mode,
                'error_message': job.error_message,
                'started_at': job.started_at.isoformat() if job.started_at else None,
                'total_items': job.total_items,
                'items_imported': job.items_imported,
                'items_failed': job.items_failed
            }
            for job, username, email in errors
        ],
        'total': len(errors)
    }), 200


@admin_logs_bp.route('/api/active-tasks', methods=['GET'])
@require_admin
def get_active_tasks():
    """
    Get currently processing tasks
    Lightweight endpoint for real-time monitoring
    """

    # Get only processing tasks
    active_tasks = db.session.query(
        ImportJob,
        User.username
    ).join(
        User, ImportJob.user_id == User.id
    ).filter(
        ImportJob.status == 'processing'
    ).order_by(
        desc(ImportJob.started_at)
    ).all()

    return jsonify({
        'active_tasks': [
            {
                'id': job.id,
                'task_id': job.celery_task_id,
                'username': username,
                'import_mode': job.import_mode,
                'total_items': job.total_items,
                'items_imported': job.items_imported,
                'started_at': job.started_at.isoformat() if job.started_at else None,
                'running_for_seconds': (
                    (datetime.utcnow() - job.started_at).total_seconds()
                    if job.started_at else 0
                )
            }
            for job, username in active_tasks
        ],
        'count': len(active_tasks)
    }), 200


@admin_logs_bp.route('/api/task/<int:task_id>', methods=['GET'])
@require_admin
def get_task_details(task_id):
    """
    Get detailed information about a specific task
    """

    job = db.session.query(
        ImportJob,
        User.username,
        User.email
    ).join(
        User, ImportJob.user_id == User.id
    ).filter(
        ImportJob.id == task_id
    ).first()

    if not job:
        return jsonify({'error': 'Task not found'}), 404

    job_obj, username, email = job

    return jsonify({
        'task': {
            'id': job_obj.id,
            'task_id': job_obj.celery_task_id,
            'user_id': job_obj.user_id,
            'username': username,
            'email': email,
            'import_mode': job_obj.import_mode,
            'listing_status': job_obj.listing_status,
            'status': job_obj.status,
            'total_items': job_obj.total_items,
            'items_imported': job_obj.items_imported,
            'items_updated': job_obj.items_updated,
            'items_failed': job_obj.items_failed,
            'started_at': job_obj.started_at.isoformat() if job_obj.started_at else None,
            'completed_at': job_obj.completed_at.isoformat() if job_obj.completed_at else None,
            'error_message': job_obj.error_message,
            'duration_seconds': (
                (job_obj.completed_at - job_obj.started_at).total_seconds()
                if job_obj.completed_at and job_obj.started_at else None
            )
        }
    }), 200
