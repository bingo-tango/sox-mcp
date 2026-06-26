"""Full smoke test using the MCP client library."""

import asyncio
import os
import tempfile

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

SOX_PATH = r"C:\Users\bwt28\.sox-o-matic\sox\sox.exe"

async def main():
    env = dict(os.environ)
    env["SOX_PATH"] = SOX_PATH

    server_params = StdioServerParameters(
        command=".venv\\Scripts\\python.exe",
        args=["sox_mcp_server.py"],
        env=env,
    )

    results = []

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # 1. Initialize
            print("[1] initialize...")
            init_result = await session.initialize()
            print(f"    OK — protocol={init_result.protocolVersion}, server={init_result.serverInfo.name} v{init_result.serverInfo.version}")
            results.append(("Initialize", True))

            # 2. List tools
            print("[2] list tools...")
            tools_resp = await session.list_tools()
            tool_names = [t.name for t in tools_resp.tools]
            print(f"    OK — {len(tools_resp.tools)} tools: {', '.join(tool_names)}")
            results.append(("List tools", len(tools_resp.tools) >= 10))

            # 3. Generate a short tone
            print("[3] call generate_tone...")
            with tempfile.TemporaryDirectory() as tmpdir:
                outfile = os.path.join(tmpdir, "tone_test.wav")
                try:
                    result = await session.call_tool("generate_tone", {
                        "frequency": 440,
                        "duration": 0.5,
                        "output_file": outfile,
                    })
                    text = ""
                    for content in result.content:
                        if hasattr(content, "text"):
                            text = content.text
                    print(f"    Response: {text[:300]}")

                    if os.path.exists(outfile):
                        size = os.path.getsize(outfile)
                        print(f"    OK — output file exists ({size} bytes)")
                        results.append(("Generate tone", True))
                    else:
                        print(f"    WARN — output file not at {outfile}")
                        results.append(("Generate tone file", False))
                except Exception as e:
                    print(f"    ERROR calling generate_tone: {e}")
                    results.append(("Generate tone", False))

                # 4. Test audio_info on the generated file
                if os.path.exists(outfile):
                    print("[4] call audio_info...")
                    try:
                        result = await session.call_tool("audio_info", {
                            "file_path": outfile,
                        })
                        text = ""
                        for content in result.content:
                            if hasattr(content, "text"):
                                text = content.text
                        print(f"    Response: {text[:300]}")
                        results.append(("Audio info", True))
                    except Exception as e:
                        print(f"    ERROR: {e}")
                        results.append(("Audio info", False))

            # 5. Test list_files
            print("[5] call list_files...")
            with tempfile.TemporaryDirectory() as tmpdir:
                # Create dummy files
                files_to_create = [
                    os.path.join(tmpdir, "test1.wav"),
                    os.path.join(tmpdir, "test2.mp3"),
                    os.path.join(tmpdir, "test3.txt"),
                ]
                for f in files_to_create:
                    with open(f, "w") as dummy:
                        dummy.write("dummy content")

                try:
                    # Test listing all files
                    result = await session.call_tool("list_files", {
                        "directory_path": tmpdir,
                    })

                    text = ""
                    for content in result.content:
                        if hasattr(content, "text"):
                            text = content.text
                    print(f"    Response: {text[:300]}")

                    # Check if it contains expected files (parsing simple text check or metadata if available)
                    # The current implementation returns metadata in the text content
                    # We'll just check if it's a success response
                    if "Found 3 files" in text:
                        print("    OK — Found correct number of files")
                        results.append(("List files (all)", True))
                    else:
                        print(f"    WARN — unexpected text: {text[:100]}")
                        results.append(("List files (all)", False))

                    # Test with extensions filter
                    result_ext = await session.call_tool("list_files", {
                        "directory_path": tmpdir,
                        "extensions": ["wav"],
                    })

                    text_ext = ""
                    for content in result_ext.content:
                        if hasattr(content, "text"):
                            text_ext = content.text

                    if "Found 1 files" in text_ext:
                         print("    OK — Extension filter works")
                         results.append(("List files (filter)", True))
                    else:
                         print(f"    WARN — extension filter failed: {text_ext[:50]}")
                         results.append(("List files (filter)", False))

                except Exception as e:
                    print(f"    ERROR calling list_files: {e}")
                    results.append(("List files", False))

    # Summary
    print("\n=== SUMMARY ===")
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")
    print(f"\n{passed}/{total} checks passed.")

asyncio.run(main())
