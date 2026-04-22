# Writing your first watcher in Python
Writing watchers for ActivityWatch is pretty easy, all you need is the `aw-client` library.

Note

These examples run the client in _testing_ mode, which means that it will try to connect to an aw-server in testing mode on the port 5666 instead of the normal 5600.

Minimal client
---------------------------------------------------------

Below is a minimal template client to quickly get started. This example will:

*   create a bucket
    
*   insert an event
    
*   fetch an event from an aw-server bucket
    
*   delete the bucket again
    

```
#!/usr/bin/env python3

from datetime import datetime, timezone

from aw_core.models import Event
from aw_client import ActivityWatchClient

# We'll run with testing=True so we don't mess up any production instance.
# Make sure you've started aw-server with the `--testing` flag as well.
client = ActivityWatchClient("test-client", testing=True)

bucket_id = "{}_{}".format("test-client-bucket", client.client_hostname)
client.create_bucket(bucket_id, event_type="dummydata")

shutdown_data = {"label": "some interesting data"}
now = datetime.now(timezone.utc)
shutdown_event = Event(timestamp=now, data=shutdown_data)
inserted_event = client.insert_event(bucket_id, shutdown_event)

events = client.get_events(bucket_id=bucket_id, limit=1)
print(events) # Should print a single event in a list

client.delete_bucket(bucket_id)

```


Reference client
-------------------------------------------------------------

Below is a example of a watcher with more in-depth comments. This example will describe how to:

*   create buckets
    
*   send events by heartbeats
    
*   insert events without heartbeats
    
*   do synchronous as well as asyncronous requests
    
*   fetch events from an aw-server bucket
    
*   delete buckets
    

```
#!/usr/bin/env python3

from time import sleep
from datetime import datetime, timezone

from aw_core.models import Event
from aw_client import ActivityWatchClient

# We'll run with testing=True so we don't mess up any production instance.
# Make sure you've started aw-server with the `--testing` flag as well.
client = ActivityWatchClient("test-client", testing=True)

# Make the bucket_id unique for both the client and host
# The convention is to use client-name_hostname as bucket name,
# but if you have multiple buckets in one client you can add a
# suffix such as client-name-event-type or similar
bucket_id = "{}_{}".format("test-client-bucket", client.client_hostname)
# A short and descriptive event type name
# Will be used by visualizers (such as aw-webui) to detect what type and format the events are in
# Can for example be "currentwindow", "afkstatus", "ping" or "currentsong"
event_type = "dummydata"

# First we need a bucket to send events/heartbeats to.
# If the bucket already exists aw-server will simply return 304 NOT MODIFIED,
# so run this every time the clients starts up to verify that the bucket exists.
# If the client was unable to connect to aw-server or something failed
# during the creation of the bucket, an exception will be raised.
client.create_bucket(bucket_id, event_type=event_type)

# Asynchronous loop example
# This context manager starts the queue dispatcher thread and stops it when done, always use it when setting queued=True.
# Alternatively you can use client.connect() and client.disconnect() instead if you prefer that
with client:
    # Now we can send some events via heartbeats
    # This will send one heartbeat every second 5 times
    sleeptime = 1
    for i in range(5):
        # Create a sample event to send as heartbeat
        heartbeat_data = {"label": "heartbeat"}
        now = datetime.now(timezone.utc)
        heartbeat_event = Event(timestamp=now, data=heartbeat_data)

        # The duration between the heartbeats will be less than pulsetime, so they will get merged.
        # The commit_interval=4.0 means that if heartbeats with the same data has a longer duration than 4 seconds it will be forced to be sent to aw-server
        # TODO: Make a section with an illustration on how heartbeats work and insert a link here
        print("Sending heartbeat {}".format(i))
        client.heartbeat(bucket_id, heartbeat_event, pulsetime=sleeptime+1, queued=True, commit_interval=4.0)

        # Sleep a second until next heartbeat
        sleep(sleeptime)

    # Give the dispatcher thread some time to complete sending the last events.
    # If we don't do this the events might possibly queue up and be sent the
    # next time the client starts instead.
    sleep(1)

# Synchronous example, insert an event
event_data = {"label": "non-heartbeat event"}
now = datetime.now(timezone.utc)
event = Event(timestamp=now, data=event_data)
inserted_event = client.insert_event(bucket_id, event)

# The event returned from insert_event has been assigned an id by aw-server
assert inserted_event.id is not None

# Fetch last 10 events from bucket
# Should be two events in order of newest to oldest
# - "shutdown" event with a duration of 0
# - "heartbeat" event with a duration of 5*sleeptime
events = client.get_events(bucket_id=bucket_id, limit=10)
print(events)

# Now lets clean up after us.
# You probably don't want this in your watchers though!
client.delete_bucket(bucket_id)

# If something doesn't work, run aw-server with --verbose to see why some request doesn't go through
# Good luck with writing your own watchers :-)

```


Writing your first watcher in Rust
-------------------------------------------------------------------------------------------------

To get started with writing watchers in Rust, you need to add the `aw-client-rust` and `aw-model` crates to your `Cargo.toml` file. The most up-to-date versions depend directly on [aw-server-rust](https://github.com/ActivityWatch/aw-server-rust).

```
[package]
name = "aw-minimal-client-rs"
version = "0.1.0"
edition = "2021"

[dependencies]
aw-client-rust = { git = "https://github.com/ActivityWatch/aw-server-rust.git", branch = "master" }
aw-models = { git = "https://github.com/ActivityWatch/aw-server-rust.git", branch = "master" }
serde_json = "1.0"
tokio = { version = "1.0", features = ["full"] }
chrono = "0.4.19"

```


Minimal client
----------------------------------------------

Below is a minimal template client to quickly get started. Mirrors the python example above. This example will:

*   create a bucket
    
*   insert an event
    
*   fetch an event from an aw-server bucket
    
*   delete the bucket again
    

```
use aw_client_rust::AwClient;
use aw_models::{Bucket, Event};
use chrono::TimeDelta;
use serde_json::{Map, Value};

async fn create_bucket(
    aw_client: &AwClient,
    bucket_id: String,
) -> Result<(), Box<dyn std::error::Error>> {
    let res = aw_client
        .create_bucket(&Bucket {
            id: bucket_id,
            bid: None,
            _type: "dummy_data".to_string(),
            data: Map::new(),
            metadata: Default::default(),
            last_updated: None,
            hostname: "".to_string(),
            client: "test-client".to_string(),
            created: None,
            events: None,
        })
        .await?;

    Ok(res)
}

#[tokio::main]
async fn main() {
    let port = 5666; // the testing port 
    let aw_client = AwClient::new("localhost", port, "test-client").unwrap();
    let bucket_id = format!("test-client-bucket_{}", aw_client.hostname);

    create_bucket(&aw_client, bucket_id.clone()).await.unwrap();

    let mut shutdown_data = Map::new();
    shutdown_data.insert(
        "label".to_string(),
        Value::String("some interesting data".to_string()),
    );

    let now = chrono::Utc::now();
    let shutdown_event = Event {
        id: None,
        timestamp: now,
        duration: TimeDelta::seconds(420),
        data: shutdown_data,
    };
    aw_client.insert_event(&bucket_id, &shutdown_event).await.unwrap();

    let events = aw_client.get_events(&bucket_id, None, None, Some(1)).await.unwrap();
    print!("{:?}", events); // prints a single event

    aw_client.delete_bucket(&bucket_id).await.unwrap();
}

```


Reference client
------------------------------------------------

Below is a example of a watcher with more in-depth comments. Mirrors the python example above. This example will describe how to: \* create buckets \* send events by heartbeats \* insert events without heartbeats \* do synchronous as well as asyncronous requests \* fetch events from an aw-server bucket \* delete buckets

```
use aw_client_rust::AwClient;
use aw_models::{Bucket, Event};
use chrono::TimeDelta;
use serde_json::{Map, Value};

async fn create_bucket(
    aw_client: &AwClient,
    bucket_id: String,
    event_type: String,
) -> Result<(), Box<dyn std::error::Error>> {
    let res = aw_client
        .create_bucket(&Bucket {
            id: bucket_id,
            bid: None,
            _type: event_type,
            data: Map::new(),
            metadata: Default::default(),
            last_updated: None,
            hostname: "".to_string(),
            client: "test-client".to_string(),
            created: None,
            events: None,
        })
        .await?;

    Ok(res)
}

#[tokio::main]
async fn main() {
    let port = 5666; // the testing port
    let aw_client = AwClient::new("localhost", port, "test-client").unwrap();
    let bucket_id = format!("test-client-bucket_{}", aw_client.hostname);
    let event_type = "dummy_data".to_string();

    // Note that in a real application, you would want to handle these errors
    create_bucket(&aw_client, bucket_id.clone(), event_type)
        .await
        .unwrap();

    let sleeptime = 1.0;
    for i in 0..5 {
        // Create a sample event to send as heartbeat
        let mut heartbeat_data = Map::new();
        heartbeat_data.insert("label".to_string(), Value::String("heartbeat".to_string()));

        let now = chrono::Utc::now();

        let heartbeat_event = Event {
            id: None,
            timestamp: now,
            duration: TimeDelta::seconds(1),
            data: heartbeat_data,
        };

        println!("Sending heartbeat event {}", i);
        // The rust client does not support queued heartbeats, or commit intervals
        aw_client
            .heartbeat(&bucket_id, &heartbeat_event, sleeptime + 1.0)
            .await
            .unwrap();

        // Sleep a second until next heartbeat (eventually drifts due to time spent in the loop)
        // You could use wait on tokio intervals to avoid drift
        tokio::time::sleep(tokio::time::Duration::from_secs_f64(sleeptime)).await;
    }

    // Sleep a bit more to allow the last heartbeat to be sent
    tokio::time::sleep(tokio::time::Duration::from_secs_f64(sleeptime)).await;

    // Synchoronous example, insert an event
    let mut event_data = Map::new();
    event_data.insert(
        "label".to_string(),
        Value::String("non-heartbeat event".to_string()),
    );
    let now = chrono::Utc::now();
    let event = Event {
        id: None,
        timestamp: now,
        duration: TimeDelta::seconds(1),
        data: event_data,
    };
    aw_client.insert_event(&bucket_id, &event).await.unwrap();

    // fetch the last 10 events
    // should include the first 5 heartbeats and the last event
    let events = aw_client
        .get_events(&bucket_id, None, None, Some(10))
        .await
        .unwrap();
    println!("Events: {:?}", events);

    // Delete the bucket
    aw_client.delete_bucket(&bucket_id).await.unwrap();
}

```


It is recommend to follow conventions and use the `aw-watcher-<name>` naming scheme for your watcher. It is also recommended for watchers to accept a `--testing` flag and a `--port <port>` flag to allow users to specify the port to connect to.