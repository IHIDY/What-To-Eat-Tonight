variable "project_name" {
  type = string
  default = "what-to-eat-cloud"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "hashed_password" {
  type        = string
  description = "SHA-256 hash of the chat login password"
  sensitive   = true
}

variable "gemini_api_key" {
  type        = string
  description = "Google Gemini API key"
  sensitive   = true
}
