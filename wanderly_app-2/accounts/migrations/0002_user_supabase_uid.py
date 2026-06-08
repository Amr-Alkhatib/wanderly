from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="supabase_uid",
            field=models.CharField(
                blank=True,
                help_text="Supabase auth.users UUID, set on first Supabase sign-in/sign-up.",
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
    ]
