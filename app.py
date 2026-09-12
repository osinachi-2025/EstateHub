import os
import hashlib
import hmac
import secrets
import smtplib
from datetime import date, time, timedelta
from email.message import EmailMessage
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from models import db, User, Property, PropertyImage, PropertyVideo, Locality, SavedProperty, Viewing, Message, Transaction, Review, SupportTicket, SubscriptionPlan, Subscription
from flask_jwt_extended import JWTManager, create_access_token, get_jwt, get_jwt_identity, jwt_required
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app=Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///properties.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = os.environ.get('SQLALCHEMY_TRACK_MODIFICATIONS', False)
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'change-this-development-secret-key-32-chars')
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', app.config['JWT_SECRET_KEY'])
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True,
)
db.init_app(app)
jwt = JWTManager(app)
database_ready = False


def user_payload(user):
    return {'id': user.id, 'full_name': user.full_name, 'email': user.email,
            'phone': user.phone, 'role': user.role}


def auth_response(user):
    token = create_access_token(identity=str(user.id), additional_claims={'role': user.role})
    return jsonify({'access_token': token, 'user': user_payload(user)}), 200


def current_agent():
    user_id = session.get('user_id')
    user = db.session.get(User, user_id) if user_id else None
    if not user or user.role != 'agent' or user.is_suspended:
        return None
    subscription = user.subscription
    if subscription and subscription.end_date and subscription.end_date < date.today():
        starter = SubscriptionPlan.query.filter_by(name='Starter').first()
        if starter:
            subscription.plan_id = starter.id
            subscription.start_date = date.today()
            subscription.end_date = None
            subscription.status = 'active'
            db.session.commit()
    return user


def current_user():
    user_id = session.get('user_id')
    return db.session.get(User, user_id) if user_id else None


@app.context_processor
def inject_current_user():
    return {'current_user': current_user()}


def require_agent():
    agent = current_agent()
    if not agent:
        return None, redirect(url_for('login', next=request.path))
    return agent, None


def current_role_user(role):
    user = current_user()
    return user if user and user.role == role and not user.is_suspended else None


def require_role(role):
    user = current_role_user(role)
    if not user:
        return None, redirect(url_for('login', next=request.path))
    return user, None


def initialize_database():
    """Create the schema and the first admin configured in .env."""
    with app.app_context():
        db.create_all()
        admin_email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
        admin_password = os.environ.get('ADMIN_PASSWORD', '').strip()
        if admin_email and admin_password:
            if len(admin_password) < 8:
                raise RuntimeError('ADMIN_PASSWORD must be at least 8 characters.')

            configured_user = User.query.filter_by(email=admin_email).first()
            admin = User.query.filter_by(role='admin').first()
            if configured_user and configured_user.role != 'admin':
                raise RuntimeError('ADMIN_EMAIL belongs to an existing non-admin user.')

            if not admin:
                admin = User(full_name='', email=admin_email, role='admin', password_hash='')
                db.session.add(admin)

            admin.full_name = os.environ.get('ADMIN_FULL_NAME', 'Celtine Administrator').strip()
            admin.email = admin_email
            admin.role = 'admin'
            if not check_password_hash(admin.password_hash, admin_password):
                admin.password_hash = generate_password_hash(admin_password)

        plan_defaults = {
            'Starter': (0, 3),
            'Professional': (15000, 30),
            'Agency': (45000, 0),
        }
        plans = {}
        for name, (price, max_listings) in plan_defaults.items():
            plan = SubscriptionPlan.query.filter_by(name=name).first()
            if not plan:
                plan = SubscriptionPlan(name=name, price=price, max_listings=max_listings)
                db.session.add(plan)
            plans[name] = plan
        db.session.flush()
        for agent in User.query.filter_by(role='agent').all():
            if not agent.subscription:
                db.session.add(Subscription(agent_id=agent.id, plan_id=plans['Starter'].id, start_date=date.today(), end_date=None, status='active'))
        db.session.commit()


@app.before_request
def ensure_database_initialized():
    global database_ready
    if not database_ready:
        initialize_database()
        database_ready = True


@app.post('/api/auth/signup')
def api_signup():
    data = request.get_json(silent=True) or {}
    full_name = str(data.get('full_name', '')).strip()
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    phone = str(data.get('phone', '')).strip() or None
    role = data.get('role', 'customer')
    if not full_name or not email or len(password) < 8:
        return jsonify({'error': 'Full name, email, and a password of at least 8 characters are required.'}), 400
    if role not in {'customer', 'agent'}:
        return jsonify({'error': 'Invalid signup role.'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with that email already exists.'}), 409
    user = User(full_name=full_name, email=email, phone=phone, role=role,
                password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    if role == 'agent':
        starter = SubscriptionPlan.query.filter_by(name='Starter').first()
        if starter:
            db.session.add(Subscription(agent_id=user.id, plan_id=starter.id, start_date=date.today(), status='active'))
            db.session.commit()
    try:
        _send_email(
            user.email,
            'Welcome to Celtine Properties',
            f'Hello {user.full_name},\n\nWelcome to Celtine Properties. Your account is ready, and you can now explore verified properties across Nigeria.\n\nLog in to get started.\n\nCeltine Properties Investment Ltd.',
        )
    except (OSError, smtplib.SMTPException, ValueError):
        app.logger.exception('Welcome email delivery failed for %s.', user.email)
    return auth_response(user)


@app.post('/api/auth/login')
def api_login():
    data = request.get_json(silent=True) or {}
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid email or password.'}), 401
    if user.is_suspended:
        return jsonify({'error': 'This account has been suspended.'}), 403
    session['user_id'] = user.id
    return auth_response(user)


@app.get('/logout')
def logout():
    session.clear()
    response = redirect(url_for('login'))
    response.delete_cookie('access_token_cookie')
    return response


@app.get('/api/auth/me')
@jwt_required()
def api_me():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({'error': 'User not found.'}), 404
    return jsonify({'user': user_payload(user), 'claims': get_jwt()}), 200


@app.post('/api/setup/admin')
def setup_admin():
    data = request.get_json(silent=True) or {}
    setup_key = os.environ.get('ADMIN_SETUP_KEY')
    if not setup_key or data.get('setup_key') != setup_key:
        return jsonify({'error': 'Invalid setup key.'}), 403
    with app.app_context():
        db.create_all()
        if User.query.filter_by(role='admin').first():
            return jsonify({'error': 'An admin user already exists.'}), 409
        full_name = str(data.get('full_name', '')).strip()
        email = str(data.get('email', '')).strip().lower()
        password = str(data.get('password', ''))
        if not full_name or not email or len(password) < 8:
            return jsonify({'error': 'Full name, email, and a password of at least 8 characters are required.'}), 400
        if User.query.filter_by(email=email).first():
            return jsonify({'error': 'An account with that email already exists.'}), 409
        admin = User(full_name=full_name, email=email, role='admin',
                     password_hash=generate_password_hash(password))
        db.session.add(admin)
        db.session.commit()
        return auth_response(admin)

@app.route('/')
def home():
    verified_query = Property.query.filter_by(status='verified')
    featured = verified_query.filter_by(is_featured=True).order_by(Property.created_at.desc()).limit(4).all()
    properties = featured or verified_query.order_by(Property.created_at.desc()).limit(4).all()
    return render_template(
        'home.html',
        properties=properties,
        verified_count=verified_query.count(),
        featured_active=bool(featured),
    )

@app.route('/buy')
def buy():
    return browse()

@app.route('/about')
def about(): 
    return render_template('/about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/not-found')
def notfound():
    return render_template('404.html')

@app.route('/browse')
def browse():
    purpose = request.args.get('purpose', '').strip().lower()
    location = request.args.get('location', '').strip()
    property_type = request.args.get('property_type', '').strip()
    min_price = request.args.get('min_price', '').strip()
    max_price = request.args.get('max_price', '').strip()
    budget = request.args.get('budget', '').strip().lower()
    bedrooms = request.args.get('bedrooms', '').strip()
    sort = request.args.get('sort', 'newest').strip().lower()

    query = Property.query.filter_by(status='verified')
    if purpose in {'rent', 'sale', 'shortlet'}:
        query = query.filter(Property.purpose == purpose)
    else:
        purpose = ''
    if location:
        location_pattern = f'%{location}%'
        query = query.filter(db.or_(
            Property.state.ilike(location_pattern),
            Property.area.ilike(location_pattern),
            Property.locality.ilike(location_pattern),
            Property.street_address.ilike(location_pattern),
            Property.landmark.ilike(location_pattern),
        ))
    if property_type:
        property_type_map = {
            'flat': 'Flat / Apartment',
            'duplex': 'Duplex',
            'bungalow': 'Bungalow',
            'land': 'Land',
            'commercial': 'Commercial',
        }
        property_type = property_type_map.get(property_type.lower(), property_type)
        query = query.filter(Property.property_type == property_type)

    def parse_price(value):
        try:
            parsed = float(value)
            return parsed if parsed >= 0 else None
        except (TypeError, ValueError):
            return None

    parsed_min = parse_price(min_price)
    parsed_max = parse_price(max_price)
    budget_ranges = {
        'under-2m': (None, 2_000_000),
        '2m-10m': (2_000_000, 10_000_000),
        'over-10m': (10_000_000, None),
    }
    if budget in budget_ranges:
        budget_min, budget_max = budget_ranges[budget]
        parsed_min = budget_min if parsed_min is None else parsed_min
        parsed_max = budget_max if parsed_max is None else parsed_max
    else:
        budget = ''
    if parsed_min is not None:
        query = query.filter(Property.price >= parsed_min)
    else:
        min_price = ''
    if parsed_max is not None:
        query = query.filter(Property.price <= parsed_max)
    else:
        max_price = ''
    if bedrooms in {'1', '2', '3'}:
        query = query.filter(Property.bedrooms >= int(bedrooms))
    elif bedrooms == '4':
        query = query.filter(Property.bedrooms >= 4)
    else:
        bedrooms = ''

    sort_options = {
        'newest': Property.created_at.desc(),
        'price_asc': Property.price.asc(),
        'price_desc': Property.price.desc(),
    }
    if sort not in sort_options:
        sort = 'newest'
    properties = query.order_by(sort_options[sort]).all()
    return render_template(
        'browse.html',
        properties=properties,
        purpose=purpose,
        location=location,
        property_type=property_type,
        min_price=min_price,
        max_price=max_price,
        budget=budget,
        bedrooms=bedrooms,
        sort=sort,
    )


@app.route('/admin-dashboard')
def admindashboard():
    admin, response = require_role('admin')
    if response:
        return response
    pending = Property.query.filter_by(status='pending').order_by(Property.created_at.desc()).limit(10).all()
    open_tickets = SupportTicket.query.filter_by(status='open').order_by(SupportTicket.created_at.desc()).limit(5).all()
    successful_revenue = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter_by(status='success').scalar()
    return render_template('admin-dashboard.html', admin=admin, users_count=User.query.count(), live_count=Property.query.filter_by(status='verified').count(), pending_count=Property.query.filter_by(status='pending').count(), revenue=successful_revenue, pending_properties=pending, open_tickets=open_tickets)

@app.route('/admin-listings')
def adminlistings():
    admin, response = require_role('admin')
    if response:
        return response
    return render_template('admin-listings.html', admin=admin, listings=Property.query.order_by(Property.created_at.desc()).all())


@app.route('/admin-listings/<int:property_id>')
def admin_listing_review(property_id):
    admin, response = require_role('admin')
    if response:
        return response
    property_record = db.session.get(Property, property_id)
    if not property_record:
        abort(404)
    amenity_labels = {
        column.name: column.name.removeprefix('has_').replace('_', ' ').title()
        for column in Property.__table__.columns if column.name.startswith('has_')
    }
    amenities = [amenity_labels[column] for column in amenity_labels if getattr(property_record, column)]
    return render_template('admin-listing-review.html', admin=admin, property=property_record, amenities=amenities)


@app.post('/admin-listings/<int:property_id>/approve')
def approve_admin_listing(property_id):
    admin, response = require_role('admin')
    if response:
        return response
    property_record = db.session.get(Property, property_id)
    if not property_record:
        abort(404)
    property_record.status = 'verified'
    db.session.commit()
    flash('Listing approved and marked as verified.', 'success')
    return redirect(url_for('admin_listing_review', property_id=property_id))


@app.post('/admin-listings/<int:property_id>/delete')
def delete_admin_listing(property_id):
    admin, response = require_role('admin')
    if response:
        return response
    property_record = db.session.get(Property, property_id)
    if not property_record:
        abort(404)
    SavedProperty.query.filter_by(property_id=property_id).delete(synchronize_session=False)
    Viewing.query.filter_by(property_id=property_id).delete(synchronize_session=False)
    Message.query.filter_by(property_id=property_id).delete(synchronize_session=False)
    Transaction.query.filter_by(property_id=property_id).update({'property_id': None}, synchronize_session=False)
    db.session.delete(property_record)
    db.session.commit()
    flash('Listing and its associated records were deleted.', 'success')
    return redirect(url_for('adminlistings'))

@app.route('/admin-reports')
def adminreports():
    admin, response = require_role('admin')
    if response:
        return response
    states = db.session.query(Property.state, db.func.count(Property.id)).group_by(Property.state).order_by(db.func.count(Property.id).desc()).all()
    total_properties = sum(count for _, count in states) or 1
    return render_template('admin-reports.html', admin=admin, state_counts=[(state or 'Unknown', count, round(count * 100 / total_properties)) for state, count in states], users=User.query.order_by(User.created_at.asc()).all())

@app.route('/admin-settings')
def adminsettings():
    admin, response = require_role('admin')
    if response:
        return response
    states = db.session.query(Property.state).filter(Property.state.isnot(None)).distinct().order_by(Property.state).all()
    types = db.session.query(Property.property_type).filter(Property.property_type.isnot(None)).distinct().order_by(Property.property_type).all()
    return render_template('admin-settings.html', admin=admin, states=[state for state, in states], property_types=[kind for kind, in types])

@app.route('/admin-support')
def adminsupport():
    admin, response = require_role('admin')
    if response:
        return response
    return render_template('admin-support.html', admin=admin, tickets=SupportTicket.query.order_by(SupportTicket.created_at.desc()).all())

@app.route('/admin-transactions')
def admintransactions():
    admin, response = require_role('admin')
    if response:
        return response
    transactions = Transaction.query.order_by(Transaction.created_at.desc()).all()
    return render_template('admin-transactions.html', admin=admin, transactions=transactions, total_processed=sum(item.amount for item in transactions if item.status == 'success'), failed_count=sum(item.status == 'failed' for item in transactions))

@app.route('/admin-users')
def adminusers():
    admin, response = require_role('admin')
    if response:
        return response
    return render_template('admin-users.html', admin=admin, users=User.query.order_by(User.created_at.desc()).all(), plans=SubscriptionPlan.query.order_by(SubscriptionPlan.price.asc()).all())


@app.post('/admin/users/<int:user_id>/subscription')
def change_agent_subscription(user_id):
    admin, response = require_role('admin')
    if response:
        return response
    agent = User.query.filter_by(id=user_id, role='agent').first_or_404()
    plan = db.session.get(SubscriptionPlan, request.form.get('plan_id', type=int))
    if not plan:
        flash('Select a valid subscription plan.', 'error')
        return redirect(url_for('adminusers'))
    start_date = date.today()
    end_date = start_date + timedelta(days=30)
    subscription = agent.subscription
    if not subscription:
        subscription = Subscription(agent_id=agent.id)
        db.session.add(subscription)
    subscription.plan_id = plan.id
    subscription.start_date = start_date
    subscription.end_date = end_date
    subscription.status = 'active'
    db.session.commit()
    flash(f'{agent.full_name} is now on the {plan.name} plan for 30 days.', 'success')
    return redirect(url_for('adminusers'))

@app.route('/agent-profile')
@app.route('/agent-profile/<int:agent_id>')
def agentprofile(agent_id=None):
    if agent_id is None:
        agent = User.query.filter_by(role='agent').order_by(User.created_at.asc()).first()
    else:
        agent = User.query.filter_by(id=agent_id, role='agent').first()
    if not agent:
        abort(404)
    listings = Property.query.filter_by(agent_id=agent.id, status='verified').order_by(Property.created_at.desc()).all()
    reviews = Review.query.filter_by(agent_id=agent.id).all()
    average_rating = round(sum(review.rating for review in reviews) / len(reviews), 1) if reviews else None
    return render_template('agent-profile.html', profile_agent=agent, listings=listings, reviews_count=len(reviews), average_rating=average_rating)

@app.route('/customer-dashboard')
def customerdashboard():
    customer, response = require_role('customer')
    if response:
        return response
    saved = SavedProperty.query.filter_by(user_id=customer.id).order_by(SavedProperty.created_at.desc()).all()
    viewings = Viewing.query.filter_by(user_id=customer.id).order_by(Viewing.viewing_date, Viewing.viewing_time).all()
    inquiries = Message.query.filter_by(sender_id=customer.id).count()
    return render_template('customer-dashboard.html', customer=customer, saved=saved[:3], saved_count=len(saved), viewings=viewings, inquiries=inquiries)

@app.route('/customer-messages')
def customermessages():
    customer, response = require_role('customer')
    if response:
        return response
    selected_agent_id = request.args.get('agent_id', type=int)
    selected_property_id = request.args.get('property_id', type=int)
    messages_query = Message.query.filter((Message.sender_id == customer.id) | (Message.receiver_id == customer.id))
    if selected_agent_id:
        messages_query = messages_query.filter((Message.sender_id == selected_agent_id) | (Message.receiver_id == selected_agent_id))
    if selected_property_id:
        messages_query = messages_query.filter_by(property_id=selected_property_id)
    messages = messages_query.order_by(Message.created_at.asc()).all()
    agents = User.query.filter_by(role='agent', is_suspended=False).order_by(User.full_name).all()
    conversation_property = db.session.get(Property, selected_property_id) if selected_property_id else None
    return render_template('customer-messages.html', customer=customer, messages=messages, agents=agents, selected_agent_id=selected_agent_id, selected_property_id=selected_property_id, conversation_property=conversation_property)


@app.post('/messages/send')
def send_message():
    sender = current_user()
    if not sender or sender.role not in {'customer', 'agent'}:
        return redirect(url_for('login'))
    receiver = db.session.get(User, request.form.get('receiver_id', type=int))
    content = request.form.get('content', '').strip()
    property_id = request.form.get('property_id', type=int)
    property_record = db.session.get(Property, property_id) if property_id else None
    if not receiver or receiver.id == sender.id or receiver.role not in {'customer', 'agent'} or not content:
        flash('Choose a recipient and enter a message.', 'error')
    elif property_record and property_record.agent_id != receiver.id and property_record.agent_id != sender.id:
        flash('This property is not associated with the selected conversation.', 'error')
    else:
        db.session.add(Message(sender_id=sender.id, receiver_id=receiver.id, property_id=property_id, content=content))
        db.session.commit()
        flash('Message sent.', 'success')
    if sender.role == 'customer':
        return redirect(url_for('customermessages', agent_id=receiver.id, property_id=property_id) if receiver else url_for('customermessages'))
    return redirect(url_for('postermessages', customer_id=receiver.id, property_id=property_id) if receiver else url_for('postermessages'))


@app.route('/checkout')
def checkout():
    customer, response = require_role('customer')
    if response:
        return response
    return render_template('checkout.html', customer=customer, transactions=Transaction.query.filter_by(user_id=customer.id).order_by(Transaction.created_at.desc()).all())

@app.route('/leads')
def leads():
    agent, response = require_agent()
    if response:
        return response
    leads_data = Message.query.filter_by(receiver_id=agent.id).order_by(Message.created_at.desc()).all()
    return render_template('leads.html', agent=agent, leads=leads_data)

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/signup')
def signup():
    return render_template('signup.html')


def _reset_code_hash(code):
    return hmac.new(app.config['SECRET_KEY'].encode(), code.encode(), hashlib.sha256).hexdigest()


def _send_email(recipient, subject, body):
    host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port = int(os.environ.get('SMTP_PORT', '587'))
    username = os.environ.get('SMTP_USERNAME') or os.environ.get('GMAIL_EMAIL')
    password = os.environ.get('SMTP_PASSWORD') or os.environ.get('GMAIL_PASSWORD')
    sender = os.environ.get('SMTP_FROM') or username
    use_ssl = os.environ.get('SMTP_USE_SSL', '').strip().lower() in {'1', 'true', 'yes'}
    if not username or not password or not sender:
        raise ValueError('SMTP credentials and sender are not configured.')

    message = EmailMessage()
    message['From'] = sender
    message['To'] = recipient
    message['Subject'] = subject
    message.set_content(body)

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(host, port, timeout=15) as smtp:
        if not use_ssl:
            smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)
    return True


def _send_reset_code(email, code):
    return _send_email(
        email,
        'Your Celtine Properties password reset code',
        f'Your Celtine Properties password reset code is {code}. It expires in 10 minutes. If you did not request this, ignore this email.',
    )


def _start_password_reset(email):
    code = f'{secrets.randbelow(1000000):06d}'
    session['password_reset'] = {
        'email': email,
        'code_hash': _reset_code_hash(code),
        'expires_at': int(__import__('time').time()) + 600,
    }
    session.modified = True
    try:
        delivered = _send_reset_code(email, code)
    except (OSError, smtplib.SMTPException, ValueError):
        app.logger.exception('Password reset email delivery failed.')
        delivered = False
    return delivered


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    submitted = False
    delivery_failed = False
    email_error = None
    if request.method == 'POST':
        submitted = True
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first() if email else None
        if user:
            delivered = _start_password_reset(user.email)
            delivery_failed = not delivered
        else:
            email_error = 'No account was found with that email address.'
    return render_template('forgot-password.html', submitted=submitted, delivery_failed=delivery_failed, email_error=email_error)


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    reset_data = session.get('password_reset') or {}
    email = reset_data.get('email', '')
    user = User.query.filter_by(email=email).first() if email else None
    code_verified = session.get('password_reset_verified') is True
    if request.method == 'POST':
        if not code_verified:
            code = request.form.get('code', '').strip()
            now = int(__import__('time').time())
            if not user or now > reset_data.get('expires_at', 0) or not hmac.compare_digest(reset_data.get('code_hash', ''), _reset_code_hash(code)):
                return render_template('reset-password.html', code_error='That code is invalid or expired.'), 400
            session['password_reset_verified'] = True
            session.modified = True
            return render_template('reset-password.html', code_verified=True, email=email)
        if not code_verified:
            return render_template('reset-password.html', code_error='Enter the code sent to your email.'), 400
        password = request.form.get('password', '')
        confirmation = request.form.get('password_confirmation', '')
        if len(password) < 8:
            return render_template('reset-password.html', code_verified=True, error='Password must be at least 8 characters.'), 400
        if password != confirmation:
            return render_template('reset-password.html', code_verified=True, error='Passwords do not match.'), 400
        if not user:
            return render_template('reset-password.html', code_error='Start a new reset request.'), 400
        user.password_hash = generate_password_hash(password)
        db.session.commit()
        session.pop('password_reset', None)
        session.pop('password_reset_verified', None)
        return redirect(url_for('login', reset='success'))

    return render_template('reset-password.html', code_verified=code_verified, email=email)


@app.post('/forgot-password/resend')
def resend_password_code():
    reset_data = session.get('password_reset') or {}
    email = reset_data.get('email', '')
    user = User.query.filter_by(email=email).first() if email else None
    if not user:
        return redirect(url_for('forgot_password'))
    delivered = _start_password_reset(user.email)
    session.pop('password_reset_verified', None)
    return render_template('forgot-password.html', submitted=True, delivery_failed=not delivered, resent=True)

@app.route('/my-listings')
def mylistings():
    agent, response = require_agent()
    if response:
        return response
    listings = Property.query.filter_by(agent_id=agent.id).order_by(Property.created_at.desc()).all()
    return render_template('my-listings.html', agent=agent, listings=listings)


@app.route('/property/<int:property_id>/edit', methods=['GET', 'POST'])
def edit_property(property_id):
    agent, response = require_agent()
    if response:
        return response
    property_record = Property.query.filter_by(id=property_id, agent_id=agent.id).first_or_404()
    amenity_fields = sorted(field.name.removeprefix('has_') for field in Property.__table__.columns if field.name.startswith('has_'))
    if request.method == 'POST':
        try:
            property_record.title = request.form.get('title', '').strip()
            property_record.purpose = request.form.get('purpose', 'rent').strip()
            property_record.state = request.form.get('state', '').strip()
            property_record.area = request.form.get('area', '').strip()
            property_record.locality = request.form.get('locality', '').strip()
            property_record.street_address = request.form.get('street_address', '').strip()
            property_record.landmark = request.form.get('landmark', '').strip() or None
            property_record.property_type = request.form.get('property_type', '').strip()
            property_record.price = float(request.form.get('price', ''))
            property_record.price_period = request.form.get('price_period', '').strip() or None
            property_record.bedrooms = int(request.form.get('bedrooms', '0') or 0)
            property_record.bathrooms = int(request.form.get('bathrooms', '0') or 0)
            property_record.size_sqm = float(request.form['size_sqm']) if request.form.get('size_sqm') else None
            property_record.parking_spaces = int(request.form.get('parking_spaces', '0') or 0)
            property_record.description = request.form.get('description', '').strip() or None
            if not property_record.title or not property_record.property_type or property_record.price <= 0:
                raise ValueError('Title, property type, and a valid price are required.')
            selected_amenities = set(request.form.getlist('amenities'))
            for amenity in amenity_fields:
                setattr(property_record, f'has_{amenity}', amenity in selected_amenities)
            db.session.commit()
            flash('Property updated successfully.', 'success')
            return redirect(url_for('mylistings'))
        except (TypeError, ValueError):
            db.session.rollback()
            flash('Please provide valid property details and price values.', 'error')
    return render_template('edit-property.html', agent=agent, property=property_record, amenity_fields=amenity_fields)


@app.post('/property/<int:property_id>/images/<int:image_id>/delete')
def delete_property_image(property_id, image_id):
    agent, response = require_agent()
    if response:
        return response
    property_record = Property.query.filter_by(id=property_id, agent_id=agent.id).first_or_404()
    image = PropertyImage.query.filter_by(id=image_id, property_id=property_record.id).first_or_404()
    db.session.delete(image)
    db.session.commit()
    flash('Property image deleted.', 'success')
    return redirect(url_for('edit_property', property_id=property_record.id))


@app.post('/property/<int:property_id>/delete')
def delete_property(property_id):
    agent, response = require_agent()
    if response:
        return response
    property_record = Property.query.filter_by(id=property_id, agent_id=agent.id).first_or_404()
    SavedProperty.query.filter_by(property_id=property_id).delete(synchronize_session=False)
    Viewing.query.filter_by(property_id=property_id).delete(synchronize_session=False)
    Message.query.filter_by(property_id=property_id).delete(synchronize_session=False)
    Transaction.query.filter_by(property_id=property_id).update({'property_id': None}, synchronize_session=False)
    db.session.delete(property_record)
    db.session.commit()
    flash('Property deleted successfully.', 'success')
    return redirect(url_for('mylistings'))

def _draft():
    return session.setdefault('property_draft', {})


def _cloudinary_ready():
    return all(os.environ.get(key) for key in ('CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET'))


def _valid_external_video(url):
    parsed = urlparse(url)
    return parsed.scheme in {'http', 'https'} and parsed.netloc.lower() in {'youtube.com', 'www.youtube.com', 'youtu.be', 'vimeo.com', 'www.vimeo.com'}


@app.route('/post-property-step-one', methods=['GET', 'POST'])
def postpropertystepone():
    agent, response = require_agent()
    if response:
        return response
    if request.method == 'POST':
        draft = _draft()
        draft.update({
            'title': request.form.get('title', '').strip(),
            'purpose': request.form.get('purpose', 'rent'),
            'state': request.form.get('state', '').strip(),
            'area': request.form.get('area', '').strip(),
            'locality': request.form.get('locality', '').strip(),
            'street_address': request.form.get('street_address', '').strip(),
            'landmark': request.form.get('landmark', '').strip(),
        })
        session.modified = True
        if not draft['title'] or not draft['state'] or not draft['area'] or not draft['locality']:
            flash('Title, state, area, and locality are required.', 'error')
        else:
            return redirect(url_for('postpropertysteptwo'))
    return render_template('post-property-step1.html', agent=agent, draft=_draft())

@app.route('/post-property-step-two', methods=['GET', 'POST'])
def postpropertysteptwo():
    agent, response = require_agent()
    if response:
        return response
    if request.method == 'POST':
        draft = _draft()
        draft.update({
            'property_type': request.form.get('property_type', '').strip(),
            'price': request.form.get('price', '').strip(),
            'price_period': request.form.get('price_period', '').strip(),
            'bedrooms': request.form.get('bedrooms', '0').strip(),
            'bathrooms': request.form.get('bathrooms', '0').strip(),
            'size_sqm': request.form.get('size_sqm', '').strip(),
            'parking_spaces': request.form.get('parking_spaces', '0').strip(),
            'description': request.form.get('description', '').strip(),
            'amenities': request.form.getlist('amenities'),
        })
        session.modified = True
        try:
            if not draft['property_type'] or float(draft['price']) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            flash('Property type and a valid price are required.', 'error')
        else:
            return redirect(url_for('postpropertystepthree'))
    return render_template('post-property-step2.html', agent=agent, draft=_draft())

@app.route('/post-property-step-three', methods=['GET', 'POST'])
def postpropertystepthree():
    agent, response = require_agent()
    if response:
        return response
    if request.method == 'POST':
        draft = _draft()
        if not draft.get('title') or not draft.get('property_type'):
            flash('Complete the first two steps before submitting.', 'error')
            return redirect(url_for('postpropertystepone'))
        if not _cloudinary_ready():
            flash('Cloudinary is not configured. Add CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET.', 'error')
            return render_template('post-property-step3.html', agent=agent, draft=draft)

        agent = current_agent()
        if not agent:
            flash('An agent account is required before publishing a property.', 'error')
            return redirect(url_for('login'))

        try:
            property_record = Property(
                agent_id=agent.id,
                title=draft['title'], purpose=draft.get('purpose', 'rent'), state=draft.get('state'),
                area=draft.get('area'), locality=draft.get('locality'), street_address=draft.get('street_address'),
                landmark=draft.get('landmark'), property_type=draft['property_type'], price=float(draft['price']),
                price_period=draft.get('price_period'), bedrooms=int(draft.get('bedrooms') or 0),
                bathrooms=int(draft.get('bathrooms') or 0), size_sqm=float(draft['size_sqm']) if draft.get('size_sqm') else None,
                parking_spaces=int(draft.get('parking_spaces') or 0), description=draft.get('description'),
            )
            amenity_fields = {field.name for field in Property.__table__.columns if field.name.startswith('has_')}
            for amenity in draft.get('amenities', []):
                field = f'has_{amenity}'
                if field in amenity_fields:
                    setattr(property_record, field, True)
            db.session.add(property_record)
            db.session.flush()

            photos = [photo for photo in request.files.getlist('photos') if photo and photo.filename]
            if len(photos) < 4:
                raise ValueError('Upload at least four property photos.')
            for index, photo in enumerate(photos):
                result = cloudinary.uploader.upload(photo, folder='celtine/properties', resource_type='image')
                db.session.add(PropertyImage(property_id=property_record.id, image_url=result['secure_url'], is_cover_photo=index == 0))

            video = request.files.get('video')
            video_url = request.form.get('video_url', '').strip()
            if video and video.filename:
                result = cloudinary.uploader.upload(video, folder='celtine/properties/videos', resource_type='video')
                db.session.add(PropertyVideo(property_id=property_record.id, video_url=result['secure_url'], source='upload'))
            elif video_url:
                if not _valid_external_video(video_url):
                    raise ValueError('Video links must be from YouTube or Vimeo.')
                source = 'vimeo' if 'vimeo.com' in video_url.lower() else 'youtube'
                db.session.add(PropertyVideo(property_id=property_record.id, video_url=video_url, source=source))
            db.session.commit()
            session.pop('property_draft', None)
            flash('Your property was submitted for verification.', 'success')
            return redirect(url_for('mylistings'))
        except (TypeError, ValueError) as error:
            db.session.rollback()
            flash(str(error), 'error')
        except Exception:
            db.session.rollback()
            app.logger.exception('Property submission failed during media upload or database commit.')
            flash('The property could not be saved because a media upload failed. Check the Cloudinary configuration and try again.', 'error')
    return render_template('post-property-step3.html', agent=agent, draft=_draft())

@app.route('/post-property')
def postproperty():
    return redirect(url_for('postpropertystepone'))

@app.route('/poster-dashboard')
def posterdashboard():
    agent, response = require_agent()
    if response:
        return response
    listings = Property.query.filter_by(agent_id=agent.id).order_by(Property.created_at.desc()).all()
    leads_count = Message.query.filter_by(receiver_id=agent.id).count()
    deals_count = Transaction.query.join(Property, Transaction.property_id == Property.id).filter(
        Property.agent_id == agent.id, Transaction.purpose == 'booking_deposit', Transaction.status == 'success'
    ).count()
    return render_template('poster-dashboard.html', agent=agent, listings=listings[:5], active_listings=sum(item.status not in {'rejected', 'flagged'} for item in listings), leads_count=leads_count, deals_count=deals_count)

@app.route('/poster-messages')
def postermessages():
    agent, response = require_agent()
    if response:
        return response
    selected_customer_id = request.args.get('customer_id', type=int)
    selected_property_id = request.args.get('property_id', type=int)
    messages_query = Message.query.filter((Message.sender_id == agent.id) | (Message.receiver_id == agent.id))
    if selected_customer_id:
        messages_query = messages_query.filter((Message.sender_id == selected_customer_id) | (Message.receiver_id == selected_customer_id))
    if selected_property_id:
        messages_query = messages_query.filter_by(property_id=selected_property_id)
    messages = messages_query.order_by(Message.created_at.asc()).all()
    customers = User.query.filter_by(role='customer', is_suspended=False).order_by(User.full_name).all()
    conversation_property = db.session.get(Property, selected_property_id) if selected_property_id else None
    return render_template('poster-messages.html', agent=agent, messages=messages, customers=customers, selected_customer_id=selected_customer_id, selected_property_id=selected_property_id, conversation_property=conversation_property)

@app.route('/poster-profile', methods=['GET', 'POST'])
def posterprofile():
    agent, response = require_agent()
    if response:
        return response
    if request.method == 'POST':
        agent.full_name = request.form.get('full_name', '').strip()
        agent.agency_name = request.form.get('agency_name', '').strip() or None
        agent.phone = request.form.get('phone', '').strip() or None
        agent.bio = request.form.get('bio', '').strip() or None
        if not agent.full_name:
            flash('Full name is required.', 'error')
        else:
            db.session.commit()
            flash('Profile updated.', 'success')
    return render_template('poster-profile.html', agent=agent)

@app.route('/property-detail')
@app.route('/property-detail/<int:property_id>')
def propertydetail(property_id=None):
    if property_id is None:
        return redirect(url_for('browse'))
    property_record = Property.query.filter_by(id=property_id, status='verified').first()
    if not property_record:
        abort(404)
    amenity_labels = {
        column.name: column.name.removeprefix('has_').replace('_', ' ').title()
        for column in Property.__table__.columns if column.name.startswith('has_')
    }
    amenities = [amenity_labels[column] for column in amenity_labels if getattr(property_record, column)]
    saved = False
    customer = current_role_user('customer')
    if customer:
        saved = SavedProperty.query.filter_by(user_id=customer.id, property_id=property_record.id).first() is not None
    return render_template('property-detail.html', property=property_record, amenities=amenities, is_saved=saved)

@app.route('/reviews')
def reviews():
    customer, response = require_role('customer')
    if response:
        return response
    return render_template('reviews.html', customer=customer, reviews=Review.query.filter_by(user_id=customer.id).order_by(Review.created_at.desc()).all())

@app.route('/saved-properties')
def savedproperties():
    customer, response = require_role('customer')
    if response:
        return response
    return render_template('saved-properties.html', customer=customer, saved=SavedProperty.query.filter_by(user_id=customer.id).order_by(SavedProperty.created_at.desc()).all())


@app.post('/properties/<int:property_id>/save')
def save_property(property_id):
    customer, response = require_role('customer')
    if response:
        return response
    property_record = db.session.get(Property, property_id)
    if not property_record:
        abort(404)
    saved = SavedProperty.query.filter_by(user_id=customer.id, property_id=property_id).first()
    if saved:
        db.session.delete(saved)
        action = 'removed from'
    else:
        db.session.add(SavedProperty(user_id=customer.id, property_id=property_id))
        action = 'added to'
    db.session.commit()
    flash(f'Property {action} saved properties.', 'success')
    return redirect(url_for('propertydetail', property_id=property_id))

@app.route('/schedule-viewing', methods=['GET', 'POST'])
def scheduleviewing():
    customer, response = require_role('customer')
    if response:
        return response
    if request.method == 'POST':
        try:
            viewing = Viewing(user_id=customer.id, property_id=int(request.form['property_id']), viewing_date=date.fromisoformat(request.form['viewing_date']), viewing_time=time.fromisoformat(request.form['viewing_time']), note=request.form.get('note', '').strip() or None)
            if not db.session.get(Property, viewing.property_id):
                raise ValueError
            db.session.add(viewing)
            db.session.commit()
            flash('Viewing request submitted.', 'success')
            return redirect(url_for('scheduleviewing'))
        except (KeyError, TypeError, ValueError):
            db.session.rollback()
            flash('Select a valid property, date, and time.', 'error')
    selected_property_id = request.args.get('property_id', type=int)
    properties = Property.query.filter_by(status='verified').order_by(Property.title).all()
    return render_template('schedule-viewing.html', customer=customer, properties=properties, selected_property_id=selected_property_id, viewings=Viewing.query.filter_by(user_id=customer.id).order_by(Viewing.viewing_date, Viewing.viewing_time).all())

@app.route('/subscrptions')
def subscriptions():
    return redirect(url_for('subscriptionplans'))


@app.route('/subscription-plans')
def subscriptionplans():
    agent, response = require_agent()
    if response:
        return response
    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.price.asc()).all()
    return render_template('subscription-plans.html', agent=agent, plans=plans, current_plan=agent.subscription.plan if agent.subscription else None)


@app.get('/<page>.html')
def legacy_template_link(page):
    """Keep prototype .html links working while pages use Flask routes."""
    wizard_routes = {
        'home': 'home',
        'browse': 'browse',
        'property-detail': 'browse',
        'agent-profile': 'agentprofile',
        'admin-dashboard': 'admindashboard',
        'admin-listings': 'adminlistings',
        'admin-reports': 'adminreports',
        'admin-settings': 'adminsettings',
        'admin-support': 'adminsupport',
        'admin-transactions': 'admintransactions',
        'admin-users': 'adminusers',
        'customer-dashboard': 'customerdashboard',
        'customer-messages': 'customermessages',
        'saved-properties': 'savedproperties',
        'schedule-viewing': 'scheduleviewing',
        'reviews': 'reviews',
        'checkout': 'checkout',
        'post-property': 'postpropertystepone',
        'post-property-step1': 'postpropertystepone',
        'post-property-step2': 'postpropertysteptwo',
        'post-property-step3': 'postpropertystepthree',
        'poster-dashboard': 'posterdashboard',
        'my-listings': 'mylistings',
        'leads': 'leads',
        'poster-messages': 'postermessages',
        'poster-profile': 'posterprofile',
        'subscription-plans': 'subscriptionplans',
    }
    if page in wizard_routes:
        return redirect(url_for(wizard_routes[page]))
    template = f'{page}.html'
    template_path = os.path.join(app.template_folder, template)
    if not os.path.isfile(template_path):
        abort(404)
    return render_template(template)

@app.route('/health')
def health():
    return 'Health check passed!', 200


if __name__ == '__main__':
    initialize_database()
    app.run(debug=True)