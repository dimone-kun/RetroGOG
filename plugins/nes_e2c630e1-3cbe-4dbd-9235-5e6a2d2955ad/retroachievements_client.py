import asyncio
import logging
from datetime import datetime, timezone

from typing import List
from galaxy.http import handle_exception, create_client_session
from galaxy.api.types import Achievement

RA_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'

class RetroachievementsClient:
    def __init__(self, user, api_key):
        self._session = create_client_session()
        self._user = user
        self._api_key = api_key

    async def get_id_by_hash(self, hash):
        with handle_exception():
            url = 'https://retroachievements.org/dorequest.php?r=gameid&m=' + hash;
            response = await self._session.request('GET', url)
            return (await response.json(content_type='text/html'))['GameID']

    async def get_earned_achievements(self, game_id):
        def achievement_parser(cheevo) -> Achievement:
            return Achievement(
                cheevo['ID'],
                cheevo['Title'],
                int(datetime.strptime(cheevo['DateEarned'], RA_DATETIME_FORMAT).replace(tzinfo=timezone.utc).timestamp())
            )

        def achievements_parser(response) -> List[Achievement]:
            return [
                achievement_parser(cheevo) for cheevo in (response['Achievements'].values()) if 'DateEarned' in cheevo
            ]

        with handle_exception():
            url = f'https://retroachievements.org/API/API_GetGameInfoAndUserProgress.php?z={self._user}&y={self._api_key}&u={self._user}&g={game_id}'
            response =  await self._session.request('GET', url)
            try :
                return achievements_parser(await response.json(content_type='text/html'))
            except ValueError:
                logging.exception("Invalid response data for:\n{url}".format(url=url))
                raise UnknownBackendResponse()
