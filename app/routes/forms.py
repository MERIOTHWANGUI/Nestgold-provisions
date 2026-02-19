# app/routes/forms.py
from wtforms import PasswordField, BooleanField, DecimalField, TextAreaField
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


class PaymentRequestForm(FlaskForm):
    name = StringField("Full Name", validators=[DataRequired(), Length(max=100)])
    phone = StringField("Phone Number", validators=[DataRequired(), Regexp(r"0[17][0-9]{8}")])
    amount = DecimalField("Amount (KES)", validators=[DataRequired(), NumberRange(min=1)], places=2)
    reference_id = StringField("Reference ID", validators=[DataRequired(), Length(max=80)])
    description = TextAreaField("Description", validators=[Length(max=500)])
    submit = SubmitField("Submit Payment Request")
