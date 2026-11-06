"""0.2.0: attempts keep every score a game reports, and the level (board) they were played on."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("kolibri_games", "0003_challenge_open_close_buttons")]

    operations = [
        migrations.AddField(model_name="attempt", name="board",
                            field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="attempt", name="values_json", field=models.TextField(default="{}")),
    ]
