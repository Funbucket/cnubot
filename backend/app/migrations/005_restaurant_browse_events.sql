-- Keep historical events; record each valid browsing action independently.
ALTER TABLE restaurant_events DROP CONSTRAINT IF EXISTS restaurant_events_event_name_check;
ALTER TABLE restaurant_events ADD CONSTRAINT restaurant_events_event_name_check
    CHECK (event_name IN ('entry', 'recommendation', 'map_click', 'browse'));
