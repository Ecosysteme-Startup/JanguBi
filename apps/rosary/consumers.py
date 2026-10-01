import json
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from apps.core.exceptions import ApplicationError
from apps.rosary.community_events import (
    action_rejected_frame,
    broadcast_frame_async,
    participant_joined_frame,
    rosary_group_name,
    session_state_frame,
)


class RosaryConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for live community rosary sessions.
    Room group: rosary_{session_id}

    Events (server → client) — définis dans ``community_events`` :
      - session_state       : {type, participants, participant_count,
                               current_decade, status, initiator_email, is_initiator}
                              envoyé au seul socket qui se connecte
      - participant_joined  : {type, user_email, participant_count}
      - decade_advanced     : {type, current_decade}
      - intention_submitted : {type, text, submitted_by}
      - rosary_ended        : {type}
      - action_rejected     : {type, action, reason}  — au seul socket refusé

    Client → server messages:
      - advance   (initiator only)
      - submit_intention
      - end       (initiator only)

    Aucun ORM ici : tout passe par ``community_services`` / ``community_selectors``.
    Les mutations diffusent elles-mêmes leur trame (après commit), de sorte que
    REST et WebSocket produisent rigoureusement le même événement.
    """

    async def connect(self):
        self.rosary_id = self.scope["url_route"]["kwargs"]["rosary_id"]
        self.group_name = rosary_group_name(self.rosary_id)
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        rosary = await self._get_rosary()
        if rosary is None or rosary.status != "active":
            await self.close(code=4004)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await self._join(rosary)

        # 1) État initial au seul nouvel arrivant : sans lui, sa liste de
        #    participants ne contiendrait que les arrivées postérieures.
        state = await self._session_state(rosary)
        await self.send(text_data=json.dumps(state))

        # 2) Puis annonce de l'arrivée à toute la salle.
        await broadcast_frame_async(
            rosary_id=self.rosary_id,
            frame=participant_joined_frame(
                user_email=self.user.email,
                participant_count=state["participant_count"],
            ),
        )

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        action = data.get("action")

        if action == "advance":
            await self._run(action, self._advance)
        elif action == "submit_intention":
            await self._run(action, self._submit_intention, data.get("text", ""))
        elif action == "end":
            await self._run(action, self._end)
        elif action:
            await self._reject(action, "Action inconnue.")

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def _run(self, action: str, handler, *args) -> None:
        """Exécute une action et convertit un refus métier en trame explicite.

        Auparavant ``advance``/``end`` étaient ignorés en silence hors
        initiateur : le client ne distinguait pas « refusé » de « perdu ».
        """
        try:
            await handler(*args)
        except ApplicationError as exc:
            await self._reject(action, exc.message)

    async def _reject(self, action: str, reason: str) -> None:
        await self.send(text_data=json.dumps(action_rejected_frame(action=action, reason=reason)))

    # ── Bridges service (la diffusion est faite par le service) ─────────────

    @database_sync_to_async
    def _advance(self) -> None:
        from apps.rosary.community_services import (
            community_rosary_advance_decade,
            community_rosary_get,
        )

        community_rosary_advance_decade(rosary=community_rosary_get(rosary_id=self.rosary_id), user=self.user)

    @database_sync_to_async
    def _submit_intention(self, text: str) -> None:
        from apps.rosary.community_services import (
            community_rosary_get,
            community_rosary_submit_intention,
        )

        community_rosary_submit_intention(
            rosary=community_rosary_get(rosary_id=self.rosary_id),
            user=self.user,
            text=text,
        )

    @database_sync_to_async
    def _end(self) -> None:
        from apps.rosary.community_services import community_rosary_end, community_rosary_get

        community_rosary_end(rosary=community_rosary_get(rosary_id=self.rosary_id), user=self.user)

    # ── Broadcast handler (appelé par le channel layer) ────────────────────

    async def rosary_broadcast(self, event):
        """Relaie telle quelle la trame construite par ``community_events``."""
        await self.send(text_data=json.dumps(event["frame"]))

    # ── Lectures / adhésion ────────────────────────────────────────────────

    @database_sync_to_async
    def _get_rosary(self):
        from apps.rosary.community_services import community_rosary_get

        try:
            return community_rosary_get(rosary_id=self.rosary_id)
        except ApplicationError:
            return None

    @database_sync_to_async
    def _join(self, rosary) -> None:
        from apps.rosary.community_services import community_rosary_join

        try:
            community_rosary_join(rosary=rosary, user=self.user)
        except ApplicationError:
            # La session a pu se clore entre le contrôle de statut et ici :
            # la fermeture sera portée par la trame `rosary_ended`.
            pass

    @database_sync_to_async
    def _session_state(self, rosary) -> dict[str, Any]:
        from apps.rosary.community_selectors import community_rosary_participants_list

        participants = [
            {"user_email": p.user.email, "joined_at": p.joined_at.isoformat()}
            for p in community_rosary_participants_list(rosary_id=rosary.pk)
        ]
        return session_state_frame(
            participants=participants,
            participant_count=len(participants),
            current_decade=rosary.current_decade,
            status=rosary.status,
            initiator_email=rosary.initiator.email if rosary.initiator_id else None,
            is_initiator=rosary.initiator_id == self.user.pk,
        )
