"""0.2.1: rooms and hand-ins for Smoke Signals."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("kolibri_games", "0004_attempt_boards_and_values")]

    operations = [
        migrations.CreateModel(
            name="Room",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("game_key", models.CharField(max_length=120)),
                ("facility_id", models.CharField(max_length=32)),
                ("challenge_id", models.IntegerField(blank=True, null=True)),
                ("code", models.CharField(max_length=8)),
                ("status", models.CharField(default="lobby", max_length=8)),
                ("host_id", models.CharField(blank=True, max_length=32, null=True)),
                ("players_json", models.TextField(default="[]")),
                ("settings_json", models.TextField(default="{}")),
                ("step", models.PositiveIntegerField(default=0)),
                ("steps", models.PositiveIntegerField(default=0)),
                ("deadline", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField()),
                ("version", models.PositiveIntegerField(default=1)),
            ],
            options={
                "indexes": [models.Index(fields=["facility_id", "game_key", "status"], name="kg_room_game")],
            },
        ),
        migrations.CreateModel(
            name="RoomEntry",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("chain", models.PositiveSmallIntegerField()),
                ("step", models.PositiveSmallIntegerField()),
                ("user_id", models.CharField(max_length=32)),
                ("kind", models.CharField(max_length=8)),
                ("content_json", models.TextField(default="{}")),
                ("auto", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField()),
                ("room", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entries",
                                           to="kolibri_games.room")),
            ],
            options={
                "unique_together": {("room", "chain", "step")},
            },
        ),
    ]
