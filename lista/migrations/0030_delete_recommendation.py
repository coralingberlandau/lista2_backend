# Generated manually to remove the Recommendation model (OpenAI feature removed)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('lista', '0029_delete_userface'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Recommendation',
        ),
    ]
