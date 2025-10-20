"""AWS ElastiCache endpoint discovery"""

import boto3
from colorama import Fore


def get_replica_endpoints(cluster_id, region='ap-south-1', profile=None):
    """Get all replica endpoints from ElastiCache replication group"""
    
    import os
    
    print(f"{Fore.CYAN}🔍 Discovering replica endpoints from AWS...")
    
    # Use explicit profile, or fall back to AWS_PROFILE env var
    effective_profile = profile or os.getenv('AWS_PROFILE')
    
    if effective_profile:
        print(f"{Fore.CYAN}   Using AWS profile: {effective_profile}")
        session = boto3.Session(profile_name=effective_profile)
        client = session.client('elasticache', region_name=region)
    else:
        # Use default credentials chain
        client = boto3.client('elasticache', region_name=region)
    
    try:
        print(f"{Fore.CYAN}   Querying replication group: {cluster_id}...")
        response = client.describe_replication_groups(
            ReplicationGroupId=cluster_id
        )
        
        print(f"{Fore.CYAN}   Found {len(response.get('ReplicationGroups', []))} replication group(s)")
        
        if not response['ReplicationGroups']:
            return []
        
        replication_group = response['ReplicationGroups'][0]
        endpoints = []
        
        node_groups = replication_group.get('NodeGroups', [])
        print(f"{Fore.CYAN}   Found {len(node_groups)} shard(s)")
        
        # Get node groups (shards)
        for node_group in node_groups:
            node_group_id = node_group.get('NodeGroupId', 'unknown')
            members = node_group.get('NodeGroupMembers', [])
            
            # Get replica endpoints only
            for member in members:
                # Check if we have endpoint info directly
                current_role = member.get('CurrentRole', '').lower()
                read_endpoint = member.get('ReadEndpoint', {})
                
                if current_role and current_role != 'primary' and read_endpoint:
                    # Direct endpoint info available
                    endpoints.append({
                        'address': read_endpoint.get('Address'),
                        'port': read_endpoint.get('Port', 6379),
                        'shard': node_group_id,
                        'role': current_role
                    })
                else:
                    # No direct endpoint - need to query cache cluster
                    cache_cluster_id = member.get('CacheClusterId')
                    if cache_cluster_id:
                        try:
                            cluster_resp = client.describe_cache_clusters(
                                CacheClusterId=cache_cluster_id,
                                ShowCacheNodeInfo=True
                            )
                            if cluster_resp['CacheClusters']:
                                cluster = cluster_resp['CacheClusters'][0]
                                
                                # Check if this is a replica
                                # For cluster-mode: role might not be exposed
                                replication_group_role = cluster.get('ReplicationGroupRole', '').lower()
                                
                                # Heuristic: In cluster-mode with multiple nodes per shard,
                                # typically XXX-001 is primary, XXX-002+ are replicas
                                is_replica = False
                                if replication_group_role == 'replica':
                                    is_replica = True
                                elif replication_group_role != 'primary':
                                    # Role unknown - use naming heuristic
                                    # Check if cluster ID ends with -002, -003, etc (not -001)
                                    if cache_cluster_id.endswith(('-002', '-003', '-004', '-005')):
                                        is_replica = True
                                
                                if is_replica:
                                    # Get endpoint from cache nodes
                                    cache_nodes = cluster.get('CacheNodes', [])
                                    if cache_nodes:
                                        endpoint = cache_nodes[0].get('Endpoint', {})
                                        if endpoint and endpoint.get('Address'):
                                            endpoints.append({
                                                'address': endpoint.get('Address'),
                                                'port': endpoint.get('Port', 6379),
                                                'shard': node_group_id,
                                                'role': 'replica'
                                            })
                        except Exception as query_err:
                            # Skip this member if we can't query it
                            print(f"{Fore.RED}   Error querying {cache_cluster_id}: {query_err}")
        
        print(f"{Fore.GREEN}   ✓ Found {len(endpoints)} replica endpoint(s)")
        return endpoints
    
    except client.exceptions.ReplicationGroupNotFoundFault:
        print(f"{Fore.RED}❌ Replication group not found: {cluster_id}")
        return []
    except Exception as e:
        print(f"{Fore.RED}❌ Error retrieving endpoints: {e}")
        return []


def get_all_endpoints(cluster_id, region='ap-south-1', primary_only=False, replica_only=False, profile=None):
    """Get endpoints with filtering options"""
    
    import os
    
    print(f"{Fore.CYAN}🔍 Discovering {'PRIMARY' if primary_only else 'ALL'} endpoints from AWS...")
    
    # Use explicit profile, or fall back to AWS_PROFILE env var
    effective_profile = profile or os.getenv('AWS_PROFILE')
    
    if effective_profile:
        print(f"{Fore.CYAN}   Using AWS profile: {effective_profile}")
        session = boto3.Session(profile_name=effective_profile)
        client = session.client('elasticache', region_name=region)
    else:
        # Use default credentials chain
        client = boto3.client('elasticache', region_name=region)
    
    try:
        print(f"{Fore.CYAN}   Querying replication group: {cluster_id}...")
        response = client.describe_replication_groups(
            ReplicationGroupId=cluster_id
        )
        
        print(f"{Fore.CYAN}   Found {len(response.get('ReplicationGroups', []))} replication group(s)")
        
        if not response['ReplicationGroups']:
            return []
        
        replication_group = response['ReplicationGroups'][0]
        endpoints = []
        
        node_groups = replication_group.get('NodeGroups', [])
        print(f"{Fore.CYAN}   Found {len(node_groups)} shard(s)")
        
        for node_group in node_groups:
            node_group_id = node_group.get('NodeGroupId', 'unknown')
            members = node_group.get('NodeGroupMembers', [])
            
            # Check all members to get endpoints
            for member in members:
                current_role = member.get('CurrentRole', '').lower()
                read_endpoint = member.get('ReadEndpoint', {})
                cache_cluster_id = member.get('CacheClusterId', '')
                
                # If endpoint info not available directly, query the cache cluster
                if not read_endpoint or not read_endpoint.get('Address'):
                    if cache_cluster_id:
                        try:
                            cluster_resp = client.describe_cache_clusters(
                                CacheClusterId=cache_cluster_id,
                                ShowCacheNodeInfo=True
                            )
                            if cluster_resp['CacheClusters']:
                                cluster = cluster_resp['CacheClusters'][0]
                                cache_nodes = cluster.get('CacheNodes', [])
                                
                                if cache_nodes:
                                    node_endpoint = cache_nodes[0].get('Endpoint', {})
                                    if node_endpoint and node_endpoint.get('Address'):
                                        read_endpoint = node_endpoint
                                
                                # Try to determine role from cluster ID pattern
                                if not current_role:
                                    # Heuristic: -001 is primary, -002+ are replicas
                                    if cache_cluster_id.endswith('-001'):
                                        current_role = 'primary'
                                    else:
                                        current_role = 'replica'
                        except Exception as e:
                            print(f"{Fore.RED}   Error querying cluster {cache_cluster_id}: {e}")
                
                # Try to get endpoint
                endpoint_address = read_endpoint.get('Address') if read_endpoint else None
                endpoint_port = read_endpoint.get('Port', 6379) if read_endpoint else 6379
                
                # If we want primaries and this is primary
                if not replica_only and current_role == 'primary':
                    if endpoint_address:
                        endpoints.append({
                            'address': endpoint_address,
                            'port': endpoint_port,
                            'role': 'primary',
                            'shard': node_group_id
                        })
                # If we want replicas/readers and this is not primary
                elif not primary_only and current_role != 'primary':
                    if endpoint_address:
                        endpoints.append({
                            'address': endpoint_address,
                            'port': endpoint_port,
                            'role': current_role,
                            'shard': node_group_id
                        })
        
        print(f"{Fore.GREEN}   ✓ Found {len(endpoints)} endpoint(s)")
        return endpoints
    
    except client.exceptions.ReplicationGroupNotFoundFault:
        print(f"{Fore.RED}❌ Replication group not found: {cluster_id}")
        return []
    except Exception as e:
        print(f"{Fore.RED}❌ Error retrieving endpoints: {e}")
        return []

