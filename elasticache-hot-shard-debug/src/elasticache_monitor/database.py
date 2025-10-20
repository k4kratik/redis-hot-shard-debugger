"""
Database module for storing and querying monitor logs.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import json


class MonitorDatabase:
    """Handle SQLite database operations for monitor logs."""
    
    def __init__(self, db_path: str = "./reports/monitor_logs.db"):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row  # Return rows as dicts
        self._create_tables()
    
    def _create_tables(self):
        """Create database schema."""
        cursor = self.conn.cursor()
        
        # Main monitor logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitor_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id TEXT NOT NULL,
                shard_name TEXT NOT NULL,
                timestamp REAL NOT NULL,
                datetime_utc TEXT NOT NULL,
                client_address TEXT,
                client_ip TEXT,
                command TEXT NOT NULL,
                key TEXT,
                key_pattern TEXT,
                args TEXT,
                raw_line TEXT,
                collection_time TEXT NOT NULL
            )
        """)
        
        # Create indexes for monitor_logs
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cluster_shard 
            ON monitor_logs(cluster_id, shard_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp 
            ON monitor_logs(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_command 
            ON monitor_logs(command)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_key_pattern 
            ON monitor_logs(key_pattern)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_client_ip 
            ON monitor_logs(client_ip)
        """)
        
        # Metadata table for tracking monitoring sessions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitoring_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_seconds INTEGER,
                num_shards INTEGER,
                total_commands INTEGER,
                config TEXT
            )
        """)
        
        # Create index for monitoring_sessions
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cluster_time 
            ON monitoring_sessions(cluster_id, start_time)
        """)
        
        self.conn.commit()
    
    def start_session(self, cluster_id: str, num_shards: int, config: Dict[str, Any]) -> int:
        """Record start of monitoring session."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO monitoring_sessions (cluster_id, start_time, num_shards, config)
            VALUES (?, ?, ?, ?)
        """, (
            cluster_id,
            datetime.utcnow().isoformat(),
            num_shards,
            json.dumps(config)
        ))
        self.conn.commit()
        return cursor.lastrowid
    
    def end_session(self, session_id: int, duration_seconds: int, total_commands: int):
        """Record end of monitoring session."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE monitoring_sessions 
            SET end_time = ?, duration_seconds = ?, total_commands = ?
            WHERE id = ?
        """, (
            datetime.utcnow().isoformat(),
            duration_seconds,
            total_commands,
            session_id
        ))
        self.conn.commit()
    
    def insert_command(self, 
                      cluster_id: str,
                      shard_name: str,
                      timestamp: float,
                      command: str,
                      client_address: str = None,
                      key: str = None,
                      key_pattern: str = None,
                      args: List[str] = None,
                      raw_line: str = None,
                      collection_time: str = None):
        """Insert a single command log entry."""
        cursor = self.conn.cursor()
        
        # Extract IP from client address
        client_ip = None
        if client_address:
            client_ip = client_address.split(':')[0] if ':' in client_address else client_address
        
        cursor.execute("""
            INSERT INTO monitor_logs (
                cluster_id, shard_name, timestamp, datetime_utc,
                client_address, client_ip, command, key, key_pattern,
                args, raw_line, collection_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cluster_id,
            shard_name,
            timestamp,
            datetime.fromtimestamp(timestamp).isoformat(),
            client_address,
            client_ip,
            command,
            key[:500] if key else None,  # Limit key length
            key_pattern,
            json.dumps(args) if args else None,
            raw_line[:1000] if raw_line else None,  # Limit raw line length
            collection_time or datetime.utcnow().isoformat()
        ))
    
    def insert_batch(self, commands: List[Dict[str, Any]]):
        """Insert multiple command log entries efficiently."""
        cursor = self.conn.cursor()
        
        data = []
        for cmd in commands:
            client_ip = None
            if cmd.get('client_address'):
                client_ip = cmd['client_address'].split(':')[0] if ':' in cmd['client_address'] else cmd['client_address']
            
            data.append((
                cmd['cluster_id'],
                cmd['shard_name'],
                cmd['timestamp'],
                datetime.fromtimestamp(cmd['timestamp']).isoformat(),
                cmd.get('client_address'),
                client_ip,
                cmd['command'],
                cmd.get('key', '')[:500] if cmd.get('key') else None,
                cmd.get('key_pattern'),
                json.dumps(cmd.get('args', [])) if cmd.get('args') else None,
                cmd.get('raw_line', '')[:1000] if cmd.get('raw_line') else None,
                cmd.get('collection_time', datetime.utcnow().isoformat())
            ))
        
        cursor.executemany("""
            INSERT INTO monitor_logs (
                cluster_id, shard_name, timestamp, datetime_utc,
                client_address, client_ip, command, key, key_pattern,
                args, raw_line, collection_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data)
        
        self.conn.commit()
    
    def query(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        """Execute a custom query."""
        cursor = self.conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchall()
    
    def get_stats(self, cluster_id: str = None, session_id: int = None) -> Dict[str, Any]:
        """Get basic statistics."""
        where_clause = ""
        params = []
        
        if session_id:
            # Get session time range
            session = self.query(
                "SELECT start_time, end_time FROM monitoring_sessions WHERE id = ?",
                (session_id,)
            )
            if session:
                where_clause = "WHERE collection_time >= ? AND collection_time <= ?"
                params = [session[0]['start_time'], session[0]['end_time']]
        elif cluster_id:
            where_clause = "WHERE cluster_id = ?"
            params = [cluster_id]
        
        cursor = self.conn.cursor()
        
        # Total commands
        cursor.execute(f"SELECT COUNT(*) as total FROM monitor_logs {where_clause}", params)
        total = cursor.fetchone()['total']
        
        # Commands by shard
        cursor.execute(f"""
            SELECT shard_name, COUNT(*) as count 
            FROM monitor_logs {where_clause}
            GROUP BY shard_name
            ORDER BY count DESC
        """, params)
        by_shard = {row['shard_name']: row['count'] for row in cursor.fetchall()}
        
        # Top commands
        cursor.execute(f"""
            SELECT command, COUNT(*) as count 
            FROM monitor_logs {where_clause}
            GROUP BY command
            ORDER BY count DESC
            LIMIT 10
        """, params)
        top_commands = {row['command']: row['count'] for row in cursor.fetchall()}
        
        # Top key patterns
        cursor.execute(f"""
            SELECT key_pattern, COUNT(*) as count 
            FROM monitor_logs {where_clause}
            WHERE key_pattern IS NOT NULL
            GROUP BY key_pattern
            ORDER BY count DESC
            LIMIT 10
        """, params)
        top_patterns = {row['key_pattern']: row['count'] for row in cursor.fetchall()}
        
        return {
            'total_commands': total,
            'commands_by_shard': by_shard,
            'top_commands': top_commands,
            'top_key_patterns': top_patterns
        }
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.commit()
            self.conn.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

