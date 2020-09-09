import asyncio
import subprocess
import sys
import json, urllib.request, os, os.path
import user_config
import datetime
import logging
import time
import hashlib
from collections import namedtuple
from typing import Any, Callable, Dict, List, NewType, Optional
from galaxy.api.consts import LicenseType, LocalGameState, Platform
from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.types import Authentication, NextStep, Game, LicenseInfo, LocalGame, GameTime, Achievement
from retroachievements_client import RetroachievementsClient

from version import __version__ as version

class Retroarch(Plugin):

    def __init__(self, reader, writer, token):
        super().__init__(Platform.NintendoEntertainmentSystem, version, reader, writer, token)
        self.game_cache = []
        self.playlist_path = user_config.emu_path + "playlists/Nintendo - Nintendo Entertainment System.lpl"
        self.proc = None
        self.game_run = ""
        if user_config.ra_user and user_config.ra_api_key:
            self.ra_client = RetroachievementsClient(user_config.ra_user, user_config.ra_api_key)
        else:
            logging.info('RetroAchievements user and API key are not provided')
            self.ra_client = None


    async def authenticate(self, stored_credentials=None):
        creds = {}
        creds["user"] = "RAUser"
        self.store_credentials(creds)
        return Authentication("RAUser", "Retroarch")

    async def pass_login_credentials(self, step, credentials, cookies):
        creds = {}
        creds["user"] = "RAUser"
        self.store_credentials(creds)
        return Authentication("RAUser", "Retroarch")

    async def get_owned_games(self):
        self.update_game_cache()
        return self.game_cache

    # Format helper for game names
    def format_game(self, game):
        game_return = game.rsplit(" (")[0]
        game_return = game_return.replace("'","")
        return game_return

    #Scans retroarch playlist for roms in rom_path and adds them to self.game_cache
    #as roms don't need to be installed, owned games and local games are the same and both run update_game_cache
    def update_game_cache(self):
        game_list = []

        if os.path.isfile(self.playlist_path):
            with open(self.playlist_path) as playlist_json:
                playlist_dict = json.load(playlist_json)
            for entry in playlist_dict["items"]:
                rom_path = entry["path"].split("#")[0]
                if os.path.isfile(rom_path):
                    provided_name = self.format_game(entry["label"])
                    game_list.append(
                        Game(
                            provided_name,
                            provided_name,
                            None,
                            LicenseInfo(LicenseType.SinglePurchase, None)
                            )
                        )

        #adds games when added while running
        for entry in game_list:
            if entry not in self.game_cache:
                self.game_cache.append(entry)
                self.add_game(entry)

        #removes games when removed while running
        for entry in self.game_cache:
            if entry not in game_list:
                self.game_cache.remove(entry)
                self.remove_game(entry.game_id)

    #runs update_game_cache in case it is started before get_owned_games. If it runs after it, it just returns self.game_cache with each game as installed
    async def get_local_games(self):
        if not self.game_cache:
            self.update_game_cache()
        local_game_list = []
        for game_entry in self.game_cache:
            local_game_list.append(LocalGame(game_entry.game_id, 1))
        return local_game_list

    # Only as placeholders so the launch game feature is recognized
    async def install_game(self, game_id):
        pass

    async def uninstall_game(self, game_id):
        pass

    def shutdown(self):
        pass

    #potentially give user more customization possibilities like starting in fullscreen etc
    async def launch_game(self, game_id):
        if os.path.isfile(self.playlist_path):
            with open(self.playlist_path) as playlist_json:
                playlist_dict = json.load(playlist_json)
        for entry in playlist_dict["items"]:
            if game_id == self.format_game(entry["label"]):
                self.update_local_game_status(LocalGame(game_id, 2))
                self.game_run = self.format_game(entry["label"])
                self.proc = subprocess.Popen(os.path.abspath(user_config.emu_path + "retroarch.exe" + " -L \"" + user_config.emu_path + "cores/" + user_config.core + "\" \"" + entry["path"]))
                break

    #imports retroarch playtime if existent. For this to work, activate "Save runtime log (aggregate)" in RetroArch settings -> Savings
    async def get_game_time(self, game_id: str, context:any):
        file_path = ""
        time = 0
        last_played = None

        if os.path.isfile(self.playlist_path):
            with open(self.playlist_path) as playlist_json:
                playlist_dict = json.load(playlist_json)
            for rom in playlist_dict["items"]:
                if game_id == self.format_game(rom["label"]):
                    file_path = user_config.emu_path + "/playlists/logs/" + rom["path"].rsplit("\\",1)[1].rsplit("#")[0].rsplit(".",1)[0] + ".lrtl"
                    if os.path.isfile(file_path):
                        with open(file_path) as json_data:
                            time_data = json.load(json_data)
                        last_played = datetime.datetime.timestamp(datetime.datetime.strptime(time_data["last_played"],'%Y-%m-%d %H:%M:%S'))
                        min_data = datetime.datetime.strptime(time_data["runtime"], '%H:%M:%S')
                        time = min_data.hour*60 + min_data.minute
        return GameTime(game_id, time, last_played)

    #checks if game is (still) running, adjusts game_cache and game_time
    def tick(self):
        try:
            if self.proc.poll() is not None:
                self.update_local_game_status(LocalGame(self.game_run, 1))
                self.update_game_time(self.get_game_time(self.game_run,None))
                self.proc = None
        except AttributeError:
            pass

        self.update_game_cache()
        self.get_local_games()

    async def get_unlocked_achievements(self, game_id: str, context: Any) -> List[Achievement]:
        if self.ra_client:
            ra_id = await self._get_retroachievement_game_id(game_id)
            logging.debug('Got retroachievements id %s', ra_id)
            if ra_id:
                return await self.ra_client.get_earned_achievements(ra_id)

        return []

    async def _get_retroachievement_game_id(self, game_id: str):
        if os.path.isfile(self.playlist_path):
            with open(self.playlist_path) as playlist_json:
                playlist_dict = json.load(playlist_json)

            for rom in playlist_dict["items"]:
                if game_id == self.format_game(rom["label"]):
                    rom_path = rom["path"]
                    if os.path.isfile(rom_path):
                        hash_md5 = hashlib.md5()
                        with open(rom_path, "rb") as f:
                            f.read(0x10)
                            hash_md5.update(f.read())
                        return hash_md5.hexdigest()
        return None


def main():
    create_and_run_plugin(Retroarch, sys.argv)

if __name__ == "__main__":
    main()
