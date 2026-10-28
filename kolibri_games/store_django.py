"""The service's store, backed by Kolibri's database."""
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
