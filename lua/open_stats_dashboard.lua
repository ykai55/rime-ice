local kAccepted = 1
local kNoop = 2

local function shell_escape(value)
  return '"' .. tostring(value):gsub('"', '\\"') .. '"'
end

local function is_windows()
  return package and package.config and package.config:sub(1, 1) == "\\"
end

local function normalize_key_repr(value)
  if not value then
    return ""
  end
  return tostring(value):lower()
end

local function build_command(url)
  if is_windows() then
    return "cmd /c start \"\" " .. shell_escape(url)
  end

  local escaped = shell_escape(url)
  return "(command -v open >/dev/null 2>&1 && open "
    .. escaped
    .. ") || (command -v xdg-open >/dev/null 2>&1 && xdg-open "
    .. escaped
    .. " >/dev/null 2>&1)"
end

local M = {}

function M.init(env)
  local config = env.engine.schema.config

  local url = config:get_string("stats_dashboard/url")
  if url == nil or url == "" then
    url = "http://127.0.0.1:8765"
  end
  env.url = url

  local trigger = config:get_string("key_binder/open_stats_dashboard")
  if trigger == nil or trigger == "" then
    trigger = "Control+Shift+s"
  end
  env.trigger_key = normalize_key_repr(trigger)
end

function M.func(key, env)
  if key:release() then
    return kNoop
  end

  if normalize_key_repr(key:repr()) ~= env.trigger_key then
    return kNoop
  end

  os.execute(build_command(env.url))
  return kAccepted
end

return M
