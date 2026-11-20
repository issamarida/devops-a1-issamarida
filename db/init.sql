-- Creates the local databases and logins: one database and one login per service.
--
-- Compose runs this on every start, so every statement checks before it creates.
-- Running it again changes nothing. It never drops a database, a table or a row.
--
-- The passwords are not written here. sqlcmd fills in $(WATCHLIST_PASSWORD) and
-- $(ALERTS_PASSWORD) from environment variables that compose reads from the
-- local-secrets volume.

IF DB_ID('watchlist') IS NULL CREATE DATABASE watchlist;
IF DB_ID('alerts') IS NULL CREATE DATABASE alerts;
GO

-- One login per service. If the login exists its password is set again, so the
-- login always matches the password in the volume.
IF SUSER_ID('watchlist_user') IS NULL
    CREATE LOGIN watchlist_user WITH PASSWORD = '$(WATCHLIST_PASSWORD)';
ELSE
    ALTER LOGIN watchlist_user WITH PASSWORD = '$(WATCHLIST_PASSWORD)';

IF SUSER_ID('alerts_user') IS NULL
    CREATE LOGIN alerts_user WITH PASSWORD = '$(ALERTS_PASSWORD)';
ELSE
    ALTER LOGIN alerts_user WITH PASSWORD = '$(ALERTS_PASSWORD)';
GO

-- Each login becomes a user in its own database only. It gets no user in the
-- other database, so SQL Server refuses it there.
-- The three roles are the ones the Azure guide gives: change the schema (to run
-- migrations), read rows and write rows.
USE watchlist;
IF USER_ID('watchlist_user') IS NULL CREATE USER watchlist_user FOR LOGIN watchlist_user;
ALTER ROLE db_ddladmin ADD MEMBER watchlist_user;
ALTER ROLE db_datareader ADD MEMBER watchlist_user;
ALTER ROLE db_datawriter ADD MEMBER watchlist_user;
GO

USE alerts;
IF USER_ID('alerts_user') IS NULL CREATE USER alerts_user FOR LOGIN alerts_user;
ALTER ROLE db_ddladmin ADD MEMBER alerts_user;
ALTER ROLE db_datareader ADD MEMBER alerts_user;
ALTER ROLE db_datawriter ADD MEMBER alerts_user;
GO
