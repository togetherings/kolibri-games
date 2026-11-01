"""0.2.0: coaches open and close challenges with buttons; set times are optional."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("kolibri_games", "0002_challenges_and_article_lists")]

    operations = [
        migrations.AddField(model_name="challenge", name="status", field=models.CharField(default="auto", max_length=8)),
        migrations.AlterField(model_name="challenge", name="opens_at", field=models.DateTimeField(blank=True, null=True)),
    ]
