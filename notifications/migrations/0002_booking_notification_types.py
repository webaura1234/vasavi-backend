# Generated manually — extends notification category/type choices.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="category",
            field=models.CharField(
                choices=[
                    ("coupon", "Coupon"),
                    ("donation", "Donation"),
                    ("user", "User"),
                    ("system", "System"),
                    ("booking", "Booking"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="notification",
            name="type",
            field=models.CharField(
                choices=[
                    ("coupon_redeemed", "Coupon redeemed"),
                    ("coupon_expired", "Coupon expired"),
                    ("coupon_nearing_expiry", "Coupon nearing expiry"),
                    ("donation_received", "Donation received"),
                    ("donation_approved", "Donation approved"),
                    ("donation_rejected", "Donation rejected"),
                    ("profile_updated", "Profile updated"),
                    ("password_changed", "Password changed"),
                    ("account_approved", "Account approved"),
                    ("system_alert", "System alert"),
                    ("new_booking", "New booking"),
                    ("payment_pending", "Payment pending"),
                    ("stay_extended", "Stay extended"),
                    ("booking_status_changed", "Booking status changed"),
                ],
                max_length=40,
            ),
        ),
    ]
