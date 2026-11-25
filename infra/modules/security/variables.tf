variable "name" {
  description = "Name prefix (surgegate)."
  type        = string
}

variable "enable_paid_services" {
  description = "GuardDuty, Security Hub and the Config recorder. false = make security-off (before the free trials end, ~26 Dec 2026)."
  type        = bool
  default     = true
}

variable "trail_retention_days" {
  description = "Days CloudTrail log files are kept in S3."
  type        = number
  default     = 90
}

# Resource types the AWS Foundational Security Best Practices controls evaluate for the services
# SurgeGate uses (Config records only these; ENIs and other high-churn types are left out).
variable "config_resource_types" {
  description = "AWS Config resource types to record (FSBP-relevant only)."
  type        = list(string)
  default = [
    "AWS::ApiGatewayV2::Stage",
    "AWS::CloudFront::Distribution",
    "AWS::CloudTrail::Trail",
    "AWS::DynamoDB::Table",
    "AWS::EC2::Instance",
    "AWS::EC2::SecurityGroup",
    "AWS::EC2::Subnet",
    "AWS::EC2::Volume",
    "AWS::EC2::VPC",
    "AWS::ECR::Repository",
    "AWS::EKS::Cluster",
    "AWS::ElastiCache::CacheCluster",
    "AWS::ElastiCache::ReplicationGroup",
    "AWS::ElasticLoadBalancingV2::LoadBalancer",
    "AWS::IAM::Policy",
    "AWS::IAM::Role",
    "AWS::IAM::User",
    "AWS::KMS::Key",
    "AWS::Kinesis::Stream",
    "AWS::Lambda::Function",
    "AWS::RDS::DBInstance",
    "AWS::S3::Bucket",
    "AWS::SecretsManager::Secret",
    "AWS::SNS::Topic",
    "AWS::SQS::Queue",
    "AWS::StepFunctions::StateMachine",
    "AWS::WAFv2::WebACL",
  ]
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
