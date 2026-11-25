# shared: long-lived, near-free resources used by every environment (container images).
# Not touched by make up / make down. Credentials from AWS_PROFILE locally, OIDC in CI.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      Env       = "shared"
      Component = "ecr"
    }
  }
}

resource "aws_ecr_repository" "service" {
  for_each = toset(var.services)

  name                 = "${var.project}/${each.key}"
  image_tag_mutability = "IMMUTABLE" # a tag (git SHA) always means the same image

  image_scanning_configuration {
    scan_on_push = true # basic scanning: free, results in the console and API
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "keep_last" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last ${var.keep_images} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.keep_images
      }
      action = { type = "expire" }
    }]
  })
}

# ---------------------------------------------------------------------------
# Account security (Day 10 Task 3): CloudTrail (free, always on) + GuardDuty, Security Hub
# (FSBP) and the Config recorder (free trials to ~26 Dec 2026; `make security-off` removes them).
# ---------------------------------------------------------------------------
module "security" {
  source               = "../../modules/security"
  name                 = var.project
  enable_paid_services = var.enable_security_services
}
