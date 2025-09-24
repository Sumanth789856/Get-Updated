-- Add new columns to users table
ALTER TABLE users ADD COLUMN gender TEXT CHECK(gender IN ('male', 'female', 'other'));
ALTER TABLE users ADD COLUMN profile_image TEXT;