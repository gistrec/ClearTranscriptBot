# ClearTranscriptBot

## Database schema

The bot uses a small PostgreSQL database for storing users and the transcripts they create.

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    tg_id INTEGER UNIQUE NOT NULL,
    name VARCHAR(127),
    registered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE transcripts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    file_path VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```
