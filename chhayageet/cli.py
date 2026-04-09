from __future__ import annotations

import argparse

from chhayageet.config import GuidanceConfig, ListenerProfile
from chhayageet.curation_engine import CurationEngine
from chhayageet.env import load_environment
from chhayageet.history_store import HistoryStore
from chhayageet.youtube_client import YouTubeClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Weekly YouTube Hindi song curator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_weekly = subparsers.add_parser("run-weekly", help="Run a weekly curation cycle")
    run_weekly.add_argument(
        "--profile",
        default=None,
        help="Path to the listener profile JSON",
    )
    run_weekly.add_argument(
        "--profile-id",
        default="default",
        help="Profile ID stored in Supabase",
    )
    run_weekly.add_argument(
        "--config-key",
        default="default",
        help="Config key stored in Supabase",
    )
    run_weekly.add_argument(
        "--credentials",
        default=None,
        help="Path to the Google OAuth client secret JSON",
    )
    run_weekly.add_argument(
        "--token",
        default=None,
        help="Path to store the OAuth token JSON",
    )
    run_weekly.add_argument(
        "--force-youtube-reauth",
        action="store_true",
        help="Ignore the saved YouTube token and run the OAuth consent flow again",
    )
    run_weekly.add_argument(
        "--verbose",
        action="store_true",
        help="Print candidates, selected songs, and playlist update details",
    )

    sync_profile = subparsers.add_parser("sync-profile", help="Upload a local profile JSON to Supabase")
    sync_profile.add_argument(
        "--profile",
        default="config/profile.json",
        help="Path to the listener profile JSON",
    )

    sync_config = subparsers.add_parser("sync-config", help="Upload a local guidance config JSON to Supabase")
    sync_config.add_argument(
        "--youtube-account",
        required=True,
        help="YouTube account key such as mandar, jay, or kedar",
    )
    sync_config.add_argument(
        "--songs-per-playlist",
        required=True,
        type=int,
        help="Number of songs to keep in each playlist",
    )
    sync_config.add_argument(
        "--playlist-prefix",
        required=True,
        help="Playlist title prefix",
    )
    sync_config.add_argument(
        "--config-key",
        default="default",
        help="Config key stored in Supabase",
    )

    auth_youtube = subparsers.add_parser("auth-youtube", help="Run YouTube OAuth and validate the saved token")
    auth_youtube.add_argument(
        "--credentials",
        default=None,
        help="Path to the Google OAuth client secret JSON",
    )
    auth_youtube.add_argument(
        "--token",
        default=None,
        help="Path to store the OAuth token JSON or pickle",
    )
    auth_youtube.add_argument(
        "--force",
        action="store_true",
        help="Force a fresh OAuth consent flow even if a token already exists",
    )
    auth_youtube.add_argument(
        "--config-key",
        default="default",
        help="Config key stored in Supabase",
    )
    return parser


def run_weekly(args: argparse.Namespace) -> int:
    history = HistoryStore()
    try:
        profile = ListenerProfile.from_file(args.profile) if args.profile else history.get_profile(args.profile_id)
        guidance = history.get_guidance(args.config_key)
        profile = profile.apply_guidance(guidance)
        youtube = YouTubeClient(
            args.credentials,
            args.token,
            youtube_account=guidance.youtube_account,
            force_reauth=args.force_youtube_reauth,
        )
        engine = CurationEngine(profile, youtube, history)
        result = engine.curate()
    finally:
        history.close()

    print(f"Account: {result['channel_title']}")
    print(f"Playlist: {result['playlist_title']} ({result['playlist_id']})")
    print(f"Songs selected: {result['selected_count']}")
    for title in result["selected_titles"]:
        print(f"- {title}")

    if args.verbose:
        print("")
        print("Candidates:")
        for item in result["candidates"]:
            reasons = ", ".join(item["rejection_reasons"]) if item["rejection_reasons"] else "eligible"
            print(
                f"[{item['score']:>5}] {item['title']} | artist={item['artist'] or '-'} | "
                f"era={item['era'] or '-'} | query={item['query']} | status={reasons}"
            )

        print("")
        print("Selected:")
        for item in result["selected"]:
            print(
                f"[{item['score']:>5}] {item['title']} | video_id={item['video_id']} | "
                f"artist={item['artist'] or '-'} | era={item['era'] or '-'} | query={item['query']}"
            )

        print("")
        print("Playlist update:")
        print(f"Added now: {len(result['playlist_update']['added'])}")
        for video_id in result["playlist_update"]["added"]:
            print(f"+ {video_id}")
        print(f"Removed: {len(result['playlist_update']['removed'])}")
        for video_id in result["playlist_update"]["removed"]:
            print(f"- {video_id}")
        print(f"Kept: {len(result['playlist_update']['kept'])}")
        for video_id in result["playlist_update"]["kept"]:
            print(f"= {video_id}")
    return 0


def sync_profile(args: argparse.Namespace) -> int:
    profile = ListenerProfile.from_file(args.profile)
    history = HistoryStore()
    try:
        history.upsert_profile(profile)
    finally:
        history.close()

    print(f"Synced profile: {profile.profile_id}")
    return 0


def sync_config(args: argparse.Namespace) -> int:
    guidance = GuidanceConfig(
        youtube_account=args.youtube_account,
        no_of_songs_per_playlist=args.songs_per_playlist,
        playlist_name_prefix=args.playlist_prefix,
    )
    history = HistoryStore()
    try:
        history.upsert_guidance(guidance, config_key=args.config_key)
    finally:
        history.close()

    print(f"Synced config: {args.config_key}")
    return 0


def auth_youtube(args: argparse.Namespace) -> int:
    history = HistoryStore()
    try:
        guidance = history.get_guidance(args.config_key)
    finally:
        history.close()
    youtube = YouTubeClient(
        args.credentials,
        args.token,
        youtube_account=guidance.youtube_account,
        force_reauth=args.force,
    )
    channel_title = youtube.authenticate()
    print(f"YouTube auth OK for: {channel_title}")
    return 0


def main() -> int:
    load_environment()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run-weekly":
        return run_weekly(args)
    if args.command == "sync-profile":
        return sync_profile(args)
    if args.command == "sync-config":
        return sync_config(args)
    if args.command == "auth-youtube":
        return auth_youtube(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
