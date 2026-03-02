# Run PowerShell script for Krill container
$CONTAINER_NAME = "krill"
$IMAGE_NAME = "krill:latest"
$PORT_MAPPING = "8055:8055"
$VOLUME_NAME = "krill_data"

# Stop and remove the container if it already exists
if (docker ps -aq -f name="^/$CONTAINER_NAME$") {
    echo "Stopping and removing existing container..."
    docker stop $CONTAINER_NAME >$null 2>&1
    docker rm $CONTAINER_NAME >$null 2>&1
}

echo "Running Krill Docker container on port 8055..."
docker run -d `
    --name $CONTAINER_NAME `
    -p $PORT_MAPPING `
    -v $VOLUME_NAME`:/app/data `
    $IMAGE_NAME

echo "Container is running in the background."
echo "Access at http://localhost:8055"
