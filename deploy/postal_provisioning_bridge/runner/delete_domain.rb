# frozen_string_literal: true
# Run inside Postal's app directory: bundle exec rails runner path/to/delete_domain.rb <fqdn>
# Required: POSTAL_ORG_PERMALINK, POSTAL_SERVER_PERMALINK (same as create_domain.rb)

begin
  name = ARGV[0].to_s.strip.downcase
  raise "missing domain argument" if name.empty?

  org = Organization.find_by(permalink: ENV.fetch("POSTAL_ORG_PERMALINK"))
  raise "organization not found" unless org

  server = org.servers.find_by(permalink: ENV.fetch("POSTAL_SERVER_PERMALINK"))
  raise "server not found" unless server

  domain = server.domains.where("LOWER(domains.name) = ?", name).first
  if domain
    uid = domain.uuid
    domain.destroy!
    puts({ ok: true, outcome: "deleted", provider_domain_id: uid }.to_json)
  else
    puts({ ok: true, outcome: "not_found" }.to_json)
  end
rescue StandardError => e
  warn e.full_message
  warn e.backtrace&.first(8)&.join("\n")
  puts({ ok: false, error_code: "rails_runner_error", error_detail: e.message.to_s[0, 2000] }.to_json)
  exit 1
end
