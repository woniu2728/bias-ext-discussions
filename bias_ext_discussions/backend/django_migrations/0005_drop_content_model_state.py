from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("discussions", "0004_remove_discussion_discussions_user_id_4b0eee_idx_and_more"),
        ("posts", "0007_drop_content_model_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="DiscussionUser"),
                migrations.DeleteModel(name="Discussion"),
            ],
        ),
    ]
