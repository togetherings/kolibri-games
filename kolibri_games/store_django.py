"""The service's store, backed by Kolibri's database."""
import json

from django.db import IntegrityError, close_old_connections, connection, transaction

from .models import ArticleList, Attempt, Challenge, GameSettings, PlayerState, Room, RoomEntry
from .service import Store


class DjangoStore(Store):
    # ------------------------------------------------------------ settings

    def settings_get(self, game_key, facility_id):
        row = GameSettings.objects.filter(game_key=game_key, facility_id=facility_id).first()
        return {"platform": row.platform, "game": row.game} if row else None

    def settings_set(self, game_key, facility_id, platform, game, by_user_id):
        row, _ = GameSettings.objects.get_or_create(game_key=game_key, facility_id=facility_id)
        row.platform = platform
        row.game = game
        row.updated_by_id = by_user_id or ""
        row.save()

    # ------------------------------------------------------------ attempts

    def attempts(self, game_key, facility_id, challenge_id, user_id=None):
        qs = Attempt.objects.filter(game_key=game_key, facility_id=facility_id, challenge_id=challenge_id)
        if user_id is not None:
            qs = qs.filter(user_id=user_id)
        return list(qs.order_by("number", "id"))

    def attempt_get(self, attempt_id):
        try:
            return Attempt.objects.filter(id=int(attempt_id)).first()
        except (TypeError, ValueError):
            return None

    def attempt_create(self, **fields):
        json_fields = {k: fields.pop(k) for k in ("public", "state", "events", "detail", "values") if k in fields}
        attempt = Attempt(**fields)
        for k, v in json_fields.items():
            setattr(attempt, k, v)
        attempt.save()
        return attempt

    def attempt_save(self, attempt):
        attempt.save()

    def attempts_void(self, game_key, facility_id, challenge_id, user_id):
        qs = Attempt.objects.filter(game_key=game_key, facility_id=facility_id, challenge_id=challenge_id, user_id=user_id)
        qs.filter(status="started").update(status="abandoned")
        qs.update(voided=True)

    # ------------------------------------------------------------ saved data

    def state_get(self, game_key, user_id):
        row = PlayerState.objects.filter(game_key=game_key, user_id=user_id).first()
        return row.data if row else None

    def state_set(self, game_key, user_id, data):
        row, _ = PlayerState.objects.get_or_create(game_key=game_key, user_id=user_id)
        row.data = data
        row.save()

    # ------------------------------------------------------------ challenges

    def challenges(self, facility_id, game_key=None):
        qs = Challenge.objects.filter(facility_id=facility_id)
        if game_key is not None:
            qs = qs.filter(game_key=game_key)
        return list(qs.order_by("opens_at", "id"))

    def challenge_get(self, challenge_id):
        try:
            return Challenge.objects.filter(id=int(challenge_id)).first()
        except (TypeError, ValueError):
            return None

    def challenge_create(self, **fields):
        json_fields = {k: fields.pop(k) for k in ("settings", "best")}
        c = Challenge(**fields)
        for k, v in json_fields.items():
            setattr(c, k, v)
        c.save()
        return c

    def challenge_save(self, challenge):
        challenge.save()

    def challenge_delete(self, challenge):
        challenge.delete()

    def challenge_set_best(self, challenge_id, best):
        # Called from a background thread, which has its own database connection.
        close_old_connections()
        try:
            Challenge.objects.filter(id=challenge_id).update(best_json=json.dumps(best, separators=(",", ":")))
        finally:
            connection.close()

    # ------------------------------------------------------------ article lists

    def article_lists(self, facility_id):
        return list(ArticleList.objects.filter(facility_id=facility_id).order_by("name", "id"))

    def article_list_get(self, list_id):
        return ArticleList.objects.filter(id=list_id).first()

    def article_list_create(self, **fields):
        return ArticleList.objects.create(**fields)

    def article_list_save(self, article_list):
        article_list.save()

    def article_list_delete(self, article_list):
        article_list.delete()

    # ------------------------------------------------------------ Smoke Signals rooms

    def rooms(self, game_key, facility_id, challenge_id, statuses):
        return list(Room.objects.filter(game_key=game_key, facility_id=facility_id, challenge_id=challenge_id,
                                        status__in=list(statuses)).order_by("id"))

    def room_codes(self, facility_id):
        return set(Room.objects.filter(facility_id=facility_id, status__in=["lobby", "playing"])
                   .values_list("code", flat=True))

    def room_get(self, room_id):
        return Room.objects.filter(id=room_id).first()

    def room_create(self, **fields):
        json_fields = {k: fields.pop(k) for k in ("players", "settings")}
        room = Room(**fields)
        for k, v in json_fields.items():
            setattr(room, k, v)
        room.save()
        return room

    def room_save(self, room):
        # One UPDATE that only matches the version that was read: if another
        # request saved the room in between, nothing changes and the caller retries.
        changed = Room.objects.filter(id=room.id, version=room.version).update(
            status=room.status, host_id=room.host_id, players_json=room.players_json,
            settings_json=room.settings_json, step=room.step, steps=room.steps, deadline=room.deadline,
            updated_at=room.updated_at, version=room.version + 1,
        )
        if changed:
            room.version += 1
        return bool(changed)

    def room_entries(self, room_id, chain=None, step=None):
        qs = RoomEntry.objects.filter(room_id=room_id)
        if chain is not None:
            qs = qs.filter(chain=chain)
        if step is not None:
            qs = qs.filter(step=step)
        return list(qs.order_by("step", "chain"))

    def room_handed_in(self, room_id, step):
        return set(RoomEntry.objects.filter(room_id=room_id, step=step).values_list("chain", flat=True))

    def room_entry_add(self, **fields):
        content = fields.pop("content")
        entry = RoomEntry(**fields)
        entry.content = content
        try:
            with transaction.atomic():
                entry.save()
        except IntegrityError:
            return False  # this chain already has a hand-in for this step
        return True

    def rooms_delete_before(self, when):
        Room.objects.filter(updated_at__lt=when).delete()

    # ---------------------------------------------------- games in channels

    def channel_saves(self, content_ids, facility_id, user_id=None):
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
