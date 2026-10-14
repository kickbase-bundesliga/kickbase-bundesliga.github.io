import requests
import json

from datetime import datetime, timedelta, timezone
from typing import Union

from kb4_api.exceptions import KickbaseLoginException, KickbaseException
from kb4_api.models._transforms import parse_date, date_to_string
from kb4_api.models.chat_item import ChatItem
from kb4_api.models.feed_item import FeedItem
from kb4_api.models.feed_item_comment import FeedItemComment
from kb4_api.models.gift import Gift
from kb4_api.models.league_data import LeagueData
from kb4_api.models.league_info import LeagueInfo
from kb4_api.models.league_me import LeagueMe
from kb4_api.models.league_user_data import LeagueUserData
from kb4_api.models.league_user_profile import LeagueUserProfile
from kb4_api.models.league_user_stats import LeagueUserStats
from kb4_api.models.lineup import LineUp
from kb4_api.models.market import Market
from kb4_api.models.market_player import MarketPlayer
from kb4_api.models.player import Player
from kb4_api.models.response.league_stats_response import LeagueStatsResponse
from kb4_api.models.user import User

class Kickbase:
    base_url: str = None
    token: str = None
    token_expire: datetime = None
    firebase_token: str = None
    firebase_token_expire: datetime = None
    user: User = None

    _username: str = None
    _password: str = None

    def __init__(self, base_url: str = 'https://api.kickbase.com/v4', firestore_project: str = 'kickbase-bdb0f',
                 google_identity_toolkit_api_key: str = None):
        self.base_url = base_url
        self.firestore_project = firestore_project
        self.google_identity_toolkit_api_key = google_identity_toolkit_api_key

    def login(self, email: str, password: str) -> (User, [LeagueData]):
        data = {
            "em": email,
            "pass": password
        }

        r = self._do_post("/user/login", data, False)

        if r.status_code != 200:
            raise KickbaseLoginException("Login fehlgeschlagen (HTTP {}). Zugangsdaten pruefen.".format(r.status_code))
        if r.status_code == 200:
            j = r.json()
            self.token = j["tkn"]
            # Token merken, damit nicht vor jeder Abfrage neu eingeloggt wird
            # (vorher wurde token_expire nie gesetzt -> Login bei jedem Request).
            try:
                self.token_expire = parse_date(j["tknex"])
            except Exception:
                self.token_expire = datetime.now(timezone.utc) + timedelta(hours=1)

            self._username = email
            self._password = password

            self.user = User(j["u"])
            league_data = [LeagueData(d) for d in j["srvl"]]
            return self.user, league_data

    def league_users(self, league: Union[str, LeagueData]) -> [LeagueUserData]:
        league_id = self._get_league_id(league)

        #r = self._do_get("/leagues/{}/users".format(league_id), False)
        r = self._do_get("/leagues/{}/settings/managers".format(league_id), True)

        if r.status_code == 200:
            return [LeagueUserData(d) for d in r.json()["us"]]
        else:
            raise KickbaseException()

    def league_user_dashboard(self, league: Union[str, LeagueData], user: Union[str, User]) -> LeagueUserProfile:
        league_id = self._get_league_id(league)
        user_id = self._get_user_id(user)

        r = self._do_get("/leagues/{}/managers/{}/dashboard".format(league_id, user_id), True)

        if r.status_code == 200:
            return LeagueUserProfile(r.json())
        else:
            raise KickbaseException()

    def league_user_performance(self, league: Union[str, LeagueData], user: Union[str, User]):
        league_id = self._get_league_id(league)
        user_id = self._get_user_id(user)

        r = self._do_get("/leagues/{}/managers/{}/performance".format(league_id, user_id), True)

        if r.status_code == 200:
            return LeagueUserProfile(r.json())
        else:
            raise KickbaseException()

    def league_user_teamcenter(self, league: Union[str, LeagueData], user: Union[str, User], matchday):
        league_id = self._get_league_id(league)
        user_id = self._get_user_id(user)

        r = self._do_get("/leagues/{}/users/{}/teamcenter?dayNumber={}".format(league_id, user_id, matchday), True)

        if r.status_code == 200:
            return LeagueUserProfile(r.json())
        else:
            raise KickbaseException()

    def _do_get(self, endpoint: str, authenticated: bool = False):
        if authenticated and  not self._is_token_valid():
            self.login(self._username, self._password)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if authenticated:
            headers["Cookie"] = self._auth_cookie()

        return requests.get(self._url_for_endpoint(endpoint), headers=headers)

    def _do_post(self, endpoint: str, data: dict, authenticated: bool = False):
        if authenticated and not self._is_token_valid():
            self.login(self._username, self._password)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if authenticated:
            headers["Cookie"] = self._auth_cookie()

        return requests.post(self._url_for_endpoint(endpoint), data=json.dumps(data), headers=headers)

    def _get_league_id(self, league: any):
        if isinstance(league, str):
            return league
        if isinstance(league, LeagueData):
            return league.id
        raise KickbaseException("league must be either type of str or LeagueData")

    def _get_player_id(self, player: any):
        if isinstance(player, str):
            return player
        if isinstance(player, Player):
            return player.id
        if isinstance(player, MarketPlayer):
            return player.id
        raise KickbaseException("player must be either type of str, Player or MarketPlayer")

    def _get_user_id(self, user: any):
        if isinstance(user, str):
            return user
        if isinstance(user, User):
            return user.id
        raise KickbaseException("user must be either type of str or User")

    def _is_token_valid(self):
        if self.token is None or self.token_expire is None:
            return False
        try:
            return self.token_expire > datetime.now(timezone.utc) + timedelta(minutes=5)
        except TypeError:  # naive datetime aus parse_date
            return self.token_expire > datetime.now() + timedelta(minutes=5)

    def _is_firebase_token_valid(self):
        if self.firebase_token is None or self.firebase_token_expire is None:
            return False
        return self.firebase_token_expire > datetime.now(timezone.utc) - timedelta(minutes=5)

    def _url_for_firestore(self, document_endpoint: str):
        return "https://firestore.googleapis.com/v1/projects/{}/databases/(default)/documents".format(
            self.firestore_project) + document_endpoint

    def _url_for_google_identity_toolkit(self, endpoint: str):
        return "https://www.googleapis.com/identitytoolkit" + endpoint

    def _url_for_endpoint(self, endpoint: str):
        return self.base_url + endpoint

    def _auth_cookie(self):
        return "kkstrauth={}".format(self.token)