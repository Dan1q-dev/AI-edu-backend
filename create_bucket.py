import os
import boto3
from botocore.exceptions import ClientError

client = boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT_URL'],
    aws_access_key_id=os.environ['S3_ACCESS_KEY'], aws_secret_access_key=os.environ['S3_SECRET_KEY'])
bucket = os.environ['S3_BUCKET']
try:
    client.head_bucket(Bucket=bucket)
except ClientError as exc:
    if exc.response['Error']['Code'] not in ('404', 'NoSuchBucket'):
        raise
    client.create_bucket(Bucket=bucket)
print('Bucket ready')
