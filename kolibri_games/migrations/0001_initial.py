from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="GameSettings",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("game_key", models.CharField(max_length=120)),
                ("facility_id", models.CharField(max_length=32)),
                ("platform_json", models.TextField(default="{}")),
                ("game_json", models.TextField(default="{}")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by_id", models.CharField(blank=True, max_length=32)),
            ],
            options={"unique_together": {("game_key", "facility_id")}},
        ),
        migrations.CreateModel(
            name="Attempt",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("game_key", models.CharField(max_length=120)),
                ("game_id", models.CharField(max_length=100)),
                ("game_version", models.CharField(max_length=40)),
                ("facility_id", models.CharField(max_length=32)),
                ("user_id", models.CharField(max_length=32)),
                ("user_name", models.CharField(max_length=255)),
                ("number", models.PositiveIntegerField()),
                ("status", models.CharField(default="started", max_length=12)),
                ("voided", models.BooleanField(default=False)),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("seconds", models.FloatField(blank=True, null=True)),
                ("score", models.FloatField(blank=True, null=True)),
                ("verified", models.BooleanField(default=False)),
                ("public_json", models.TextField(default="{}")),
                ("vstate_json", models.TextField(default="{}")),
                ("events_json", models.TextField(default="[]")),
                ("detail_json", models.TextField(default="{}")),
            ],
        ),
        migrations.AddIndex(
            model_name="attempt",
            index=models.Index(fields=["game_key", "facility_id", "user_id"], name="kg_attempt_player"),
        ),
        migrations.AddIndex(
            model_name="attempt",
            index=models.Index(fields=["game_key", "facility_id", "status"], name="kg_attempt_status"),
        ),
        migrations.CreateModel(
            name="PlayerState",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("game_key", models.CharField(max_length=120)),
                ("user_id", models.CharField(max_length=32)),
                ("data_json", models.TextField(default="null")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"unique_together": {("game_key", "user_id")}},
        ),
    ]
