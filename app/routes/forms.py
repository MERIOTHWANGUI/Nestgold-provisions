# app/routes/forms.py
from wtforms import PasswordField, BooleanField, DecimalField, TextAreaField, DateField, RadioField
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField
from wtforms.validators import DataRequired, Length, Regexp, NumberRange

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(max=100)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')


class SubscriptionForm(FlaskForm):
    name = StringField("Full Name", validators=[DataRequired(), Length(max=100)])
    phone = StringField("Phone Number", validators=[DataRequired(), Regexp(r"0[17][0-9]{8}")])
    location = StringField("Delivery Location", validators=[DataRequired(), Length(max=200)])
    delivery_day = SelectField("Preferred Delivery Day", choices=[
        ("Monday", "Monday"),
        ("Tuesday", "Tuesday"),
        ("Wednesday", "Wednesday"),
        ("Thursday", "Thursday"),
        ("Friday", "Friday")
    ], validators=[DataRequired()])
    submit = SubmitField("Proceed to Payment")


class TrackingLookupForm(FlaskForm):
    tracking_id = StringField("Tracking ID / Reference", validators=[DataRequired(), Length(max=100)])
    submit = SubmitField("Track")


class ConfirmManualPaymentForm(FlaskForm):
    channel = SelectField('Instruction Channel', choices=[
        ('', 'Not Set'),
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
    ])
    transaction_reference = StringField("Transaction Reference", validators=[Length(max=100)])
    admin_notes = TextAreaField("Admin Notes", validators=[Length(max=500)])
    submit = SubmitField('Confirm')


class DeliveryUpdateForm(FlaskForm):
    status = SelectField(
        "Delivery Update",
        choices=[("Delivered", "Delivered"), ("Skipped", "Skipped"), ("Cancelled", "Cancelled")],
        validators=[DataRequired()],
    )
    delivery_date = DateField("Delivery Date", format="%Y-%m-%d", validators=[DataRequired()])
    notes = TextAreaField("Delivery Notes", validators=[Length(max=500)])
    submit = SubmitField("Save Delivery")


class PaymentConfigForm(FlaskForm):
    mpesa_paybill = StringField(
        "M-Pesa Paybill",
        validators=[DataRequired(), Length(max=40)],
        render_kw={"placeholder": "e.g. 247247"},
    )
    mpesa_account_name = StringField(
        "M-Pesa Account Name",
        validators=[DataRequired(), Length(max=100)],
        render_kw={"placeholder": "e.g. NestGold Provisions"},
    )
    mpesa_account_number = StringField(
        "M-Pesa Account Number",
        validators=[DataRequired(), Length(max=80)],
        render_kw={"placeholder": "e.g. NESTGOLD-12345"},
    )
    bank_name = StringField(
        "Alternative Bank (Optional)",
        validators=[Length(max=100)],
        render_kw={"placeholder": "e.g. Equity Bank"},
    )
    instructions_footer = TextAreaField("Instruction Footer", validators=[Length(max=500)])
    submit = SubmitField("Save Payment Details")

class FeedbackForm(FlaskForm):
    name = StringField("Your Name", validators=[DataRequired(), Length(max=100)])
    rating = RadioField(
        "Star Rating",
        choices=[(5, "5"), (4, "4"), (3, "3"), (2, "2"), (1, "1")],
        coerce=int,
        validators=[DataRequired()],
    )
    comment = TextAreaField("Comment", validators=[DataRequired(), Length(max=500)])
    submit = SubmitField("Send Feedback")

