

# Lambda Triggers
# S3: ide-bd-eu-west-2
# arn:aws:s3:::ide-bd-eu-west-2
# Details
# Bucket arn: arn:aws:s3:::ide-bd-eu-west-2
# Event types: s3:ObjectCreated:*
# isComplexStatement: No
# Notification name: 6f3e069f-3208-4b4c-bdbb-e70ea297be98
# Prefix: uploads/
# Service principal: s3.amazonaws.com
# Source account: 519845866060
# Statement ID: lambda-13d31248-4445-4738-9d29-21d154a89d18
#                     Suffix: .pdf

# Environment variables
# ALLOWED_SUFFIXES: PDF, JPEG, PNG, TIFF
# SNS_TOPIC_ARN: arn:aws:sns:eu-west-2:519845866060:AmazonTextract-ide-events
# TEXTRACT_ROLE_ARN: arn:aws:iam::519845866060:role/TextractServiceRole-ide

import json
import boto3
import os
import urllib.parse
import time


def lambda_handler(event, context):
    print("=== LAMBDA START ===")

    textract = boto3.client('textract')
    print("✅ Textract client created")

    # Get environment variables
    SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
    TEXTRACT_ROLE_ARN = os.environ.get('TEXTRACT_ROLE_ARN')

    print(f"Environment variables:")
    print(f"  SNS_TOPIC_ARN: {SNS_TOPIC_ARN}")
    print(f"  TEXTRACT_ROLE_ARN: {TEXTRACT_ROLE_ARN}")

    for record in event['Records']:
        print("=== PROCESSING RECORD ===")

        # Parse S3 event
        bucket = record['s3']['bucket']['name']
        key = urllib.parse.unquote_plus(record['s3']['object']['key'], encoding='utf-8')

        print(f"S3 Event Details:")
        print(f"  Bucket: {bucket}")
        print(f"  Key: {key}")
        print(f"  Event Name: {record['eventName']}")
        print(f"  AWS Region: {record['awsRegion']}")

        # Validate file extension
        print("=== VALIDATING FILE ===")
        allowed_extensions = ['.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff']
        file_extension = key.lower().split('.')[-1]
        print(f"File extension: {file_extension}")

        if f'.{file_extension}' not in allowed_extensions:
            print(f"❌ Skipping file with unsupported extension: {file_extension}")
            continue

        print("✅ File extension is valid")

        # Check file size (this might be where it hangs)
        print("=== CHECKING FILE SIZE ===")
        try:
            s3_client = boto3.client('s3')
            print("✅ S3 client created")

            print(f"Calling head_object for {bucket}/{key}")
            response = s3_client.head_object(Bucket=bucket, Key=key)
            print("✅ head_object call completed")

            file_size = response['ContentLength']
            print(f"File size: {file_size} bytes")

            if file_size > 500 * 1024 * 1024:  # 500MB limit for async
                print(f"❌ File too large: {file_size} bytes (max 500MB)")
                continue

        except Exception as e:
            print(f"❌ Error checking file: {e}")
            continue

        print("=== CALLING TEXTRACT ===")

        # Prepare Textract parameters
        document_location = {
            "S3Object": {
                "Bucket": bucket,
                "Name": key
            }
        }

        notification_channel = {
            "SNSTopicArn": SNS_TOPIC_ARN,
            "RoleArn": TEXTRACT_ROLE_ARN
        }

        print(f"About to call start_document_text_detection...")

        try:
            # Call Textract
            resp = textract.start_document_text_detection(
                DocumentLocation=document_location,
                NotificationChannel=notification_channel,
            )

            print(f"🎉 SUCCESS! Started Textract job: JobId={resp['JobId']}")

        except Exception as e:
            print(f"❌ TEXTRACT ERROR:")
            print(f"  Error Type: {type(e).__name__}")
            print(f"  Error Message: {str(e)}")
            raise

    print("=== LAMBDA END ===")
    return {"statusCode": 200, "body": "Success"}
