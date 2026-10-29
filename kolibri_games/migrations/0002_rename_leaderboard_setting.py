"""Version 0.1.1 calls the "leaderboard" platform setting "scoreboard". Keep coaches' choices."""
import json

from django.db import migrations


def _rename(apps, old, new):
    GameSettings = apps.get_model("kolibri_games", "GameSettings")
    for row in GameSettings.objects.all():
        try:
            platform = json.loads(row.platform_json or "{}")
        except ValueError:
            continue
        if isinstance(platform, dict) and old in platform:
            platform.setdefault(new, platform[old])
            del platform[old]
            row.platform_json = json.dumps(platform)
            row.save(update_fields=["platform_json"])


def forwards(apps, schema_editor):
    _rename(apps, "leaderboard", "scoreboard")


def backwards(apps, schema_editor):
    _rename(apps, "scoreboard", "leaderboard")


class Migration(migrations.Migration):
    dependencies = [("kolibri_games", "0001_initial")]
    operations = [migrations.RunPython(forwards, backwards)]
