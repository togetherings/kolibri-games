"""The service's store, backed by Kolibri's database."""
import json

from .models import Attempt, GameSettings, PlayerState
from .service import Store


class DjangoStore(Store):
    def settings_get(self, game_key, facility_id):
        row = GameSettings.objects.filter(game_key=game_key, facility_id=facility_id).first()
        return {"platform": row.platform, "game": row.game} if row else None

    def settings_set(self, game_key, facility_id, platform, game, by_user_id):
        row, _ = GameSettings.objects.get_or_create(game_key=game_key, facility_id=facility_id)
        row.platform = platform
        row.game = game
        row.updated_by_id = by_user_id or ""
        row.save()

    def attempts(self, game_key, facility_id, user_id=None):
        qs = Attempt.objects.filter(game_key=game_key, facility_id=facility_id)
        if user_id is not None:
            qs = qs.filter(user_id=user_id)
        return list(qs.order_by("number", "id"))

    def attempt_get(self, attempt_id):
        try:
            return Attempt.objects.filter(id=int(attempt_id)).first()
        except (TypeError, ValueError):
            return None

    def attempt_create(self, **fields):
        json_fields = {k: fields.pop(k) for k in ("public", "vstate", "events", "detail")}
        attempt = Attempt(**fields)
        for k, v in json_fields.items():
            setattr(attempt, k, v)
        attempt.save()
        return attempt

    def attempt_save(self, attempt):
        attempt.save()

    def attempts_void(self, game_key, facility_id, user_id):
        qs = Attempt.objects.filter(game_key=game_key, facility_id=facility_id, user_id=user_id)
        qs.filter(status="started").update(status="abandoned")
        qs.update(voided=True)

    def state_get(self, game_key, user_id):
        row = PlayerState.objects.filter(game_key=game_key, user_id=user_id).first()
        return row.data if row else None

    def state_set(self, game_key, user_id, data):
        row, _ = PlayerState.objects.get_or_create(game_key=game_key, user_id=user_id)
        row.data = data
        row.save()

    def lesson_saves(self, content_ids, facility_id, user_id=None):
        """Kolibri keeps what an HTML5 app saves (SCORM, xAPI, localStorage) in
        ContentSummaryLog.extra_fields["contentState"]. Those logs sync between
        Kolibri servers, so scoreboards include learners who played elsewhere."""
        if not content_ids:
            return []
        from kolibri.core.logger.models import ContentSummaryLog

        qs = ContentSummaryLog.objects.filter(content_id__in=list(content_ids), user__facility_id=facility_id)
        if user_id is not None:
            qs = qs.filter(user_id=user_id)
        saves = []
        for log in qs.values("user_id", "user__full_name", "user__username", "content_id", "extra_fields"):
            extra = log["extra_fields"] or {}
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except ValueError:
                    extra = {}
            if not isinstance(extra, dict):
                continue
            saves.append(
                {
                    "user_id": str(log["user_id"]),
                    "user_name": log["user__full_name"] or log["user__username"] or "?",
                    "content_id": str(log["content_id"]),
                    "content_state": extra.get("contentState"),
                }
            )
        return saves
