insert into public.config (config_key, guidance)
values (
    'default',
    '{
      "youtube_account": "mandar",
      "no_of_songs_per_playlist": 12,
      "playlist_name_prefix": "Chaayageet",
      "preferred_model": "none"
    }'::jsonb
)
on conflict (config_key) do update
set guidance = excluded.guidance;

select config_key, guidance
from public.config
where config_key = 'default';
