import os

from openai import OpenAI
CI_TOKEN='eyJhbGciOiJSUzI1NiJ9.eyJjbHVzdGVyIjoiQTUyRCIsInJvdXRpbmdfcnVsZSI6Ii9pZGJjb25maWcvMWViNjVmZGYtOTY0My00MTdmLTk5NzQtYWQ3MmNhZTBlMTBmL3YxL3Nzby9ydWxlcy9EZWZhdWx0UnVsZSIsInByaXZhdGUiOiJleUpqZEhraU9pSktWMVFpTENKbGJtTWlPaUpCTVRJNFEwSkRMVWhUTWpVMklpd2lZV3huSWpvaVpHbHlJbjAuLnBxdm51V3JKN29UMGQyZDY1NnRXcmcuVENPcEJSQjZuQWc3aVEtcTlZQjFuRU1pRG5nUFVkOEs0STk3aUdwVWltb2FUaHpTVlh6c0JOdTU3czhOUjRYTG5YWmczTUJrdGJnSlNZZ0JwcTA3eGVVYll4NklPcjFhd1JKN1NMWGhjZjgtNWtIem1jRHRPdjdFTTZ5amxmMVgtc3VRZXVhcEd1VGpHLWo4U1A0QnkzV1BUSE9ya2ktQmJnNnNXemx6b00xd2xsajFxT2FtWEFsc015b2Z4Mlh3Sng3bDNQOWU2bVdkelEtVmNDWFd0TUVUaDVtYUxCZXVZV3FzdzRpZkhpTGt4UTVLRVJxdXVoT0ZmLXgxODJwdHY1MzJfaVYtYlRpaDNOQ1RlTE02dWIxdGczMk5fSHNMSDVPZ3NxM194MWVOSjViVkVGSGZTZ1kzNXd3SzRXNFlaVzE3WVdWS0NIVVhoNU5jd3l3eDFWSjJDQnN4VUxZMUVKT21nZWZiSGw3bUd3bU9xeS1oVmF1dmtGYVRxcG1FRnpGOElURXJUZnh2RWdyTVNUVEtJMlF2VDNvcXRmZmVoWl9kNHRDeTNkcjdtMDhFOXY4NXVxb2dqNzFVZmVQdlluR2lJLUhibEIyWE93WVNfT2FzNFl0SG4yNTdqaFZvQUZSd0szNEFhMm9maVRXdnBsZlhBWmhrYWhrQktFVVJqYUFtR1F5RVphenNraUZBeHc3VWpGUW1mYnRLOHZWdkl0RTg1d0Z2YjRRLmNadDN3dUFIYjB4MkxTUGF0cF84ZnciLCJyZWZlcmVuY2VfaWQiOiIyZTU1YTY5Zi04NDQyLTRlOTEtYjg2ZS0wNTExYjEzYWFiNWMiLCJhbXIiOlsicHdkIl0sImlzcyI6Imh0dHBzOi8vaWRicm9rZXJidHMud2ViZXguY29tL2lkYiIsInRva2VuX3R5cGUiOiJCZWFyZXIiLCJjbGllbnRfaWQiOiJDOGY4ZDY5MzY5MzhmZWI5MTRiOTcxMTFjMGU1NjMwZWY1NzQ1NWI3M2ViNmUzMzZhMzNlNzRiNjI0ZDc5NmU1NiIsImF1ZCI6IkM4ZjhkNjkzNjkzOGZlYjkxNGI5NzExMWMwZTU2MzBlZjU3NDU1YjczZWI2ZTMzNmEzM2U3NGI2MjRkNzk2ZTU2IiwidXNlcl90eXBlIjoidXNlciIsInRva2VuX2lkIjoiQWFaM3IwWVRRd05qUTBOR1V0T0dNeU9TMDBOV1l4TFdJNU9ETXRZelF6TmpRelpUWXlOVEl6TVdSbFlqWmlZVFF0T1dJNSIsIm9yZ19pZCI6IjFlYjY1ZmRmLTk2NDMtNDE3Zi05OTc0LWFkNzJjYWUwZTEwZiIsImlkcF9pc3MiOiIvaWRiY29uZmlnLzFlYjY1ZmRmLTk2NDMtNDE3Zi05OTc0LWFkNzJjYWUwZTEwZi92MS9zYW1sbWV0YWRhdGEvcmVtb3RlL2lkcC82ODc0NzQ3MDczM0EyRjJGNzM3MzZGMkQ2NDYyNjI2NjY1NjMzNzY2MkU3MzczNkYyRTY0NzU2RjczNjU2Mzc1NzI2OTc0NzkyRTYzNkY2RDJGNzM2MTZENkMzMjJGNzM3MDJGNDQ0OTQ2NTg1MDRCNDgzOTRCMzQ1MzQxNTU0MzM5NTAzNTMwMzczNTJGNkQ2NTc0NjE2NDYxNzQ2MSIsInVzZXJfbW9kaWZ5X3RpbWVzdGFtcCI6IjIwMjUwOTEwMDgyNDA2LjY1MloiLCJyZWFsbSI6IjFlYjY1ZmRmLTk2NDMtNDE3Zi05OTc0LWFkNzJjYWUwZTEwZiIsImNpc191dWlkIjoiZjUzZmE4MDEtNzRkMy00Mjc1LWIzMzMtY2Y4YjgwM2EyYTA5IiwiZXhwaXJ5X3RpbWUiOjE3NzQ1NTU3NDA2ODAsImV4cCI6MTc3NDU1NTc0MDY4MH0.Qaf4-jdFDa0ivNJGS-fLF8C4mAfWLhrVRQHTTwhPgzAXF3T4dY_memZhYq53Jg-7443A4Ls88pPFsbjHDcl540VSaJI0aTb_cNvYgY8XUDtyr4nCs-2yyBuoyUGOhj04L7RXCpL6ZWDFMPxe3fnsoVT0OvzrLiX9ADK2QpzxfFPuVRyM-A_W__bciawM8NdQLkTvMIINXqiffNH0Wvt2u_2pIl2dzxTI4a1pie-K9XS70lXg6B6S8tPEQxI1x61KjWwYDSKAWy6DLYLlWpSqy-n1z2qj15Dsv1opVYx5qDiHwEB_pvaO3dD-6wpHgyVGqrlwS_XICdEkH6VIeeOeJQ'

# Initialize the client with LLM Proxy base URL
client = OpenAI(
    base_url="https://llm-proxy.us-east-2.int.infra.intelligence.webex.com/openai/v1",
    api_key=CI_TOKEN,
    default_headers={"x-cisco-app": "my-app"},
)

# Create a response
response = client.responses.create(
    model="gpt-4.1",
    input=[
        {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": "You are a helpful assistant.",
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Explain load balancing in simple terms.",
                }
            ],
        },
    ],
)

# Print the response
print(response.output[0].content[0].text)
