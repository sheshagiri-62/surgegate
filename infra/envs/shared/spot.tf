# EC2 Spot's service-linked role (account-wide, free). Karpenter launches Spot nodes through
# EC2 Fleet, which needs this role; it doesn't exist in a new account until the first Spot
# launch, and the Karpenter controller is not allowed to create IAM roles (Day 10 Task 4: the
# demo load generators run on Spot).
resource "aws_iam_service_linked_role" "spot" {
  aws_service_name = "spot.amazonaws.com"
  description      = "EC2 Spot (Karpenter Spot nodes for the demo load generators)"
  tags             = { Component = "eks" }
}
