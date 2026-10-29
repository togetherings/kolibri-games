"""0.2.0: challenges, article lists, and attempts that belong to free play or a challenge."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("kolibri_games", "0001_initial")]

    operations = [
        migrations.RemoveIndex(model_name="attempt", name="kg_attempt_player"),
        migrations.RemoveIndex(model_name="attempt", name="kg_attempt_status"),
        migrations.RemoveField(model_name="attempt", name="verified"),
        migrations.RenameField(model_name="attempt", old_name="vstate_json", new_name="state_json"),
        migrations.AddField(
            model_name="attempt", name="challenge_id", field=models.IntegerField(blank=True, null=True)
        ),
        migrations.AddIndex(
            model_name="attempt",
            index=models.Index(fields=["game_key", "facility_id", "challenge_id", "user_id"], name="kg_attempt_player"),
        ),
        migrations.CreateModel(
            name="Challenge",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("game_key", models.CharField(max_length=120)),
                ("facility_id", models.CharField(max_length=32)),
                ("class_id", models.CharField(max_length=32)),
                ("class_name", models.CharField(max_length=255)),
                ("title", models.CharField(max_length=100)),
                ("settings_json", models.TextField(default="{}")),
                ("counts", models.CharField(default="first", max_length=8)),
                ("time_limit", models.PositiveIntegerField(default=0)),
                ("opens_at", models.DateTimeField()),
                ("closes_at", models.DateTimeField(blank=True, null=True)),
                ("created_by_id", models.CharField(blank=True, max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("best_json", models.TextField(default="{}")),
            ],
            options={"indexes": [models.Index(fields=["facility_id", "game_key"], name="kg_challenge_game")]},
        ),
        migrations.CreateModel(
            name="ArticleList",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("facility_id", models.CharField(max_length=32)),
                ("name", models.CharField(max_length=100)),
                ("titles", models.TextField(default="")),
                ("created_by_id", models.CharField(blank=True, max_length=32)),
                ("updated_at", models.DateTimeField()),
            ],
        ),
    ]
