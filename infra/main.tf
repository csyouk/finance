provider "aws" {
  region  = "us-west-2"
  profile = "finance"
}

# resource "aws_iam_role" "iam_for_lambda" {
#   name = "iam_for_lambda"
# 
#   assume_role_policy = <<EOF
# {
#   "Version": "2012-10-17",
#   "Statement": [
#     {
#       "Action": "sts:AssumeRole",
#       "Principal": {
#         "Service": "lambda.amazonaws.com"
#       },
#       "Effect": "Allow",
#       "Sid": ""
#     }
#   ]
# }
# EOF
# }

data "aws_iam_role" "iam_for_lambda" {
  name = "iam_for_lambda"
}

variable "s3_bucket" {
  default = "finance.brogrammer.xyz"
}

variable "lambda_filename" {
  default = "fetch_asset_values.zip"
}

# NOTE: I would like to execute the following commands before creating the
# `fetch_asset_values_lambda` resource, but I haven't figured out how to do so.
resource "null_resource" "build_lambda" {
  provisioner "local-exec" {
    command = <<EOF
      pip install -r ../requirements.txt -t build
      cp lambda.py build/
      cd build
      zip -r ../fetch_asset_values.zip .
    EOF
  }
}

resource "aws_lambda_function" "fetch_asset_values_lambda" {
  s3_bucket        = "${var.s3_bucket}"
  s3_key           = "${var.lambda_filename}"
  function_name    = "fetch_asset_values"
  role             = "${data.aws_iam_role.iam_for_lambda.arn}"
  handler          = "lambda.handler"
  source_code_hash = "${var.lambda_filename}"
  runtime          = "python3.6"
  timeout          = 180

  depends_on = ["null_resource.build_lambda"]
}

resource "aws_cloudwatch_event_target" "event_target_lambda" {
  target_id = "${aws_lambda_function.fetch_asset_values_lambda.id}"
  rule      = "${aws_cloudwatch_event_rule.event_rule.name}"
  arn       = "${aws_lambda_function.fetch_asset_values_lambda.arn}"
  input     = "{}"
}

resource "aws_cloudwatch_event_rule" "event_rule" {
  name                = "event_rule"
  description         = "Periodic event"
  schedule_expression = "cron(0 * * * ? *)"
}

resource "aws_sqs_queue" "request_import_stock_values" {
  name                      = "finance-request-import-stock-values"
  delay_seconds             = 0
  max_message_size          = 262144
  message_retention_seconds = 345600
}

# NOTE: Could we launch a Lambda to install packages via pip and zip them up?
# TODO: Make a process to package the code and upload to S3

