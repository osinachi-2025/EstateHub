"""
Celtine Properties — Database Models
=====================================
Plain SQLAlchemy models (works with Flask-SQLAlchemy too — see note at
the bottom of the file). Kept deliberately simple: one table per real
concept on the site, short columns, obvious names.

Covers every role from the prototype:
  - Customer   -> browses, saves, books viewings, messages, pays, reviews
  - Poster     -> is a User with role="agent"; owns Properties, has a Subscription
  - Admin      -> is a User with role="admin"; reviews/approves listings & tickets

Updated for the 3-step "Post a Property" flow:
  Step 1 (Name & Address)   -> title, purpose, state, area, locality, street_address, landmark
  Step 2 (Features)         -> type, price, bedrooms, bathrooms, size, amenities, description
  Step 3 (Photos & Videos)  -> PropertyImage rows + PropertyVideo rows
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# ---------------------------------------------------------------------------
# USERS  (customers, agents/posters, and admins all live in one table,
# separated by the `role` column — simplest way to model 3 user types)
# ---------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20))
    role = db.Column(db.String(20), default="customer")   # "customer" | "agent" | "admin"

    # Agent-only profile info (left blank for customers/admins)
    agency_name = db.Column(db.String(150))
    bio = db.Column(db.Text)
    is_verified = db.Column(db.Boolean, default=False)     # ID/CAC verified badge
    is_suspended = db.Column(db.Boolean, default=False)    # admin can suspend a user

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relationships
    properties = db.relationship("Property", back_populates="agent")
    saved = db.relationship("SavedProperty", back_populates="user")
    viewings = db.relationship("Viewing", back_populates="user")
    property_views = db.relationship("PropertyView", back_populates="user")
    reviews_written = db.relationship("Review", foreign_keys="Review.user_id", back_populates="user")
    subscription = db.relationship("Subscription", back_populates="agent", uselist=False)
    tickets = db.relationship("SupportTicket", back_populates="user")

    def __repr__(self):
        return f"<User {self.full_name} ({self.role})>"


# ---------------------------------------------------------------------------
# PROPERTIES
# Fields are grouped by which step of the "Post a Property" wizard fills them.
# ---------------------------------------------------------------------------
class Property(db.Model):
    __tablename__ = "properties"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # --- Step 1: Name & Address ---
    title = db.Column(db.String(200), nullable=False)
    purpose = db.Column(db.String(10), default="rent")       # "rent" | "sale" | "shortlet"
    state = db.Column(db.String(50))                          # e.g. "Lagos"
    area = db.Column(db.String(50))                            # e.g. "Lekki" — the broad area picked first
    locality = db.Column(db.String(100))                        # e.g. "Osapa London" — the specific spot,
                                                            #   populated by the dynamic dropdown once `area` is chosen
    street_address = db.Column(db.String(200))
    landmark = db.Column(db.String(150))                         # optional, e.g. "Behind Shoprite"

    # --- Step 2: Features ---
    property_type = db.Column(db.String(50))                    # e.g. "Flat", "Duplex", "Land"
    price = db.Column(db.Float, nullable=False)
    price_period = db.Column(db.String(20))                      # e.g. "year" — blank for sales
    bedrooms = db.Column(db.Integer, default=0)
    bathrooms = db.Column(db.Integer, default=0)
    size_sqm = db.Column(db.Float)
    parking_spaces = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)

    # Amenities as plain booleans — simpler to read than a separate join table
    has_24hr_power = db.Column(db.Boolean, default=False)
    has_estate_security = db.Column(db.Boolean, default=False)
    has_swimming_pool = db.Column(db.Boolean, default=False)
    has_bq = db.Column(db.Boolean, default=False)
    has_fitted_kitchen = db.Column(db.Boolean, default=False)
    has_parking_space = db.Column(db.Boolean, default=False)
    has_gym = db.Column(db.Boolean, default=False)
    has_garage = db.Column(db.Boolean, default=False)
    has_gated_community = db.Column(db.Boolean, default=False)
    has_water_supply = db.Column(db.Boolean, default=False)
    has_air_conditioning = db.Column(db.Boolean, default=False)
    has_internet = db.Column(db.Boolean, default=False)
    has_cctv = db.Column(db.Boolean, default=False)
    has_elevator = db.Column(db.Boolean, default=False)
    has_balcony = db.Column(db.Boolean, default=False)
    has_furnished = db.Column(db.Boolean, default=False)
    has_garden = db.Column(db.Boolean, default=False)
    has_fireplace = db.Column(db.Boolean, default=False)
    has_solar_power = db.Column(db.Boolean, default=False)
    has_generator = db.Column(db.Boolean, default=False)
    has_water_heater = db.Column(db.Boolean, default=False)
    has_clubhouse = db.Column(db.Boolean, default=False)
    has_playground = db.Column(db.Boolean, default=False)
    has_church_nearby = db.Column(db.Boolean, default=False)
    has_school_nearby = db.Column(db.Boolean, default=False)
    has_hospital_nearby = db.Column(db.Boolean, default=False)
    has_shopping_mall_nearby = db.Column(db.Boolean, default=False)
    has_mosque_nearby = db.Column(db.Boolean, default=False)
    has_public_transport_nearby = db.Column(db.Boolean, default=False)
    has_park_nearby = db.Column(db.Boolean, default=False)

    # --- Step 3: Photos & Videos are separate tables below (one-to-many) ---

    # Set by admin after review, not by the poster
    status = db.Column(db.String(20), default="pending")         # "pending" | "verified" | "flagged" | "rejected"
    is_featured = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relationships
    agent = db.relationship("User", back_populates="properties")
    images = db.relationship("PropertyImage", back_populates="property", cascade="all, delete-orphan")
    videos = db.relationship("PropertyVideo", back_populates="property", cascade="all, delete-orphan")
    saved_by = db.relationship("SavedProperty", back_populates="property")
    viewings = db.relationship("Viewing", back_populates="property")
    views = db.relationship("PropertyView", back_populates="property", cascade="all, delete-orphan")
    messages = db.relationship("Message", back_populates="property")

    def __repr__(self):
        return f"<Property {self.title} - ₦{self.price}>"


class PropertyView(db.Model):
    """Persisted property page views for vendor analytics."""
    __tablename__ = "property_views"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    session_key = db.Column(db.String(128), nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)

    property = db.relationship("Property", back_populates="views")
    user = db.relationship("User", back_populates="property_views")


class PropertyImage(db.Model):
    """One row per uploaded photo — Step 3 of the post-property wizard."""
    __tablename__ = "property_images"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"), nullable=False)
    image_url = db.Column(db.String(300), nullable=False)
    is_cover_photo = db.Column(db.Boolean, default=False)   # which photo shows first on the listing card

    property = db.relationship("Property", back_populates="images")


class PropertyVideo(db.Model):
    """One row per walkthrough video — either an uploaded file or a pasted link (YouTube/Vimeo)."""
    __tablename__ = "property_videos"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"), nullable=False)
    video_url = db.Column(db.String(300), nullable=False)
    source = db.Column(db.String(20), default="upload")       # "upload" | "youtube" | "vimeo"

    property = db.relationship("Property", back_populates="videos")


# ---------------------------------------------------------------------------
# LAGOS AREAS -> LOCALITIES  (powers the dynamic Area/Locality dropdown
# on Step 1. Optional table — you can also just hardcode the list in the
# frontend like the prototype does, and skip this table entirely.)
# ---------------------------------------------------------------------------
class Locality(db.Model):
    """
    Self-referential: a top-level row has parent_id = None (e.g. "Lekki"),
    and its localities point back to it (e.g. "Osapa London" -> parent "Lekki").
    Selecting an Area in the UI means: show me all Localities where parent_id = area.id
    """
    __tablename__ = "localities"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("localities.id"), nullable=True)

    children = db.relationship("Locality", backref="parent", remote_side=[id])


# ---------------------------------------------------------------------------
# SAVED PROPERTIES  (customer's favorites/wishlist)
# ---------------------------------------------------------------------------
class SavedProperty(db.Model):
    __tablename__ = "saved_properties"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="saved")
    property = db.relationship("Property", back_populates="saved_by")


# ---------------------------------------------------------------------------
# VIEWINGS  ("Schedule a Viewing" bookings)
# ---------------------------------------------------------------------------
class Viewing(db.Model):
    __tablename__ = "viewings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"), nullable=False)

    viewing_date = db.Column(db.Date, nullable=False)
    viewing_time = db.Column(db.Time, nullable=False)
    note = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending")     # "pending" | "confirmed" | "completed" | "cancelled"

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="viewings")
    property = db.relationship("Property", back_populates="viewings")


# ---------------------------------------------------------------------------
# MESSAGES  (customer <-> agent chat, optionally tied to a property)
# ---------------------------------------------------------------------------
class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"))  # nullable — not every chat is about a listing

    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])
    property = db.relationship("Property", back_populates="messages")


# ---------------------------------------------------------------------------
# TRANSACTIONS  (booking deposits, plan upgrades, etc.)
# ---------------------------------------------------------------------------
class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"))  # nullable — plan payments have no property

    amount = db.Column(db.Float, nullable=False)
    purpose = db.Column(db.String(30))                        # "booking_deposit" | "subscription" | "service_fee"
    status = db.Column(db.String(20), default="pending")       # "pending" | "success" | "failed"
    reference = db.Column(db.String(50), unique=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")
    property = db.relationship("Property")


# ---------------------------------------------------------------------------
# REVIEWS  (customer rates an agent after a viewing/deal)
# ---------------------------------------------------------------------------
class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)     # who wrote it
    agent_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)    # who it's about

    rating = db.Column(db.Integer, nullable=False)   # 1–5
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id], back_populates="reviews_written")
    agent = db.relationship("User", foreign_keys=[agent_id])


# ---------------------------------------------------------------------------
# SUBSCRIPTION PLANS  (Starter / Professional / Agency)
# ---------------------------------------------------------------------------
class SubscriptionPlan(db.Model):
    __tablename__ = "subscription_plans"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)         # "Starter", "Professional", "Agency"
    price = db.Column(db.Float, default=0)
    max_listings = db.Column(db.Integer, default=3)

    subscriptions = db.relationship("Subscription", back_populates="plan")


class Subscription(db.Model):
    """Which plan an agent is currently on."""
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("subscription_plans.id"), nullable=False)

    start_date = db.Column(db.Date, default=datetime.utcnow)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(20), default="active")      # "active" | "expired" | "cancelled"

    agent = db.relationship("User", back_populates="subscription")
    plan = db.relationship("SubscriptionPlan", back_populates="subscriptions")


# ---------------------------------------------------------------------------
# SUPPORT TICKETS  (admin support queue)
# ---------------------------------------------------------------------------
class SupportTicket(db.Model):
    __tablename__ = "support_tickets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    priority = db.Column(db.String(10), default="low")        # "low" | "medium" | "urgent"
    status = db.Column(db.String(20), default="open")          # "open" | "closed"

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="tickets")


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------
# 1. Using Flask-SQLAlchemy instead? Swap the top of this file for:
#       from flask_sqlalchemy import SQLAlchemy
#       db = SQLAlchemy()
#       class User(db.Model): ...
#    and replace Column/relationship/ForeignKey with db.Column/db.relationship/db.ForeignKey.
#
# 2. To create the tables:
#       from sqlalchemy import create_engine
#       engine = create_engine("sqlite:///celtine.db")
#       Base.metadata.create_all(engine)
#
# 3. One User table covers all 3 roles (customer/agent/admin) via `role` —
#    keeps the schema small instead of 3 separate near-identical tables.
#
# 4. The `Locality` table is optional. The frontend prototype hardcodes the
#    Area -> Locality list in JavaScript, which is simplest for a small,
#    fixed set of Lagos neighborhoods. Add this table later only if you
#    want admins to manage the area list from the database instead of code.