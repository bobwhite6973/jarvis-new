# ██████╗   ███████╗ ██╗    ██╗ ███████╗            ██████╗    ██████╗             ██████╗   █████╗ ████████╗███████╗███████╗
# ██╔══██╗ ██╔════╝ ██║    ██║ ██╔════╝            ██╔══██╗ ██╔═══██╗          ██╔════╝   ██╔══██╗╚══██╔══╝██╔════╝██╔════╝
# ██║    ██║ █████╗     ██║    ██║ ███████╗            ██║    ██║ ██║      ██║         ███████║   ██║   █████╗     ███████╗
# ██║    ██║ ██╔══╝    ╚██╗  ██╔╝ ╚════██║           ██║    ██║ ██║      ██║         ██╔══██║   ██║   ██╔══╝     ╚════██║
# ██████╔╝ ███████╗  ╚████╔╝  ███████║            ██████╔╝╚██████╔╝          ╚██████╗██║      ██║   ██║   ███████╗███████║
# ╚═════╝  ╚══════╝    ╚═══╝     ╚══════╝            ╚═════╝    ╚═════╝             ╚═════╝╚═╝      ╚═╝   ╚═╝   ╚══════╝╚══════╝

#  Made With 💓 By - Sree ( Devs Do Code )
#  YouTube Channel: https://www.youtube.com/@devsdocode

"""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

      - Support: https://buymeacoffee.com/devsdocode
      - Patreon: https://patreon.com/DevsDoCode

"""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

#  For any questions or concerns, reach out to us via our social media handles.
#  Our top choice for contact is Telegram: https://t.me/devsdocode
#  You can also find us on other platforms listed above. We're here to help!

# ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
# ██░██░█░▄▄▀█▀▄▀█░█▀█░▄▄█░▄▄▀█░▄▄███░▄▄▀█░▄▄▀█░▄▄███░████░▄▄█░▄▄▀█▀▄▀█░▀▀█░░█░▀▀█░░░░░░░░░░░░
# ██░▄▄░█░▀▀░█░█▀█░▄▀█░▄▄█░▀▀▄█▄▄▀███░▀▀░█░▀▀▄█░▄▄███░▄▄░█░▄▄█░▀▀░█░█▀█░█░░█░██░█░░░░░░░░░░░░░
# ██░██░█▄██▄██▄██▄█▄█▄▄▄█▄█▄▄█▄▄▄███▄██▄█▄█▄▄█▄▄▄███▄██▄█▄▄▄█▄█▄▄██▄██▄█░░░█░░█░█░░░░░░░░░░░░
# ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀


#  - YouTube Channel: https://www.youtube.com/@hackersareherewhereareyou
#  - Discord Server: https://discord.gg/2BGD2Cuk34                         
#  ------------------------------------------------------------------------------
#  Dive into the world of coding with Devs Do Code & HACKERS ARE HERE WHERE ARE YOU- where passion meets programming!
#  Make sure to hit that Subscribe button to stay tuned for exciting content!

#  Pro Tip: For optimal performance and a seamless experience, we recommend using
#  the default library versions demonstrated in this demo. Your coding journey just
#  got even better! Happy coding!
#  ----------------------------------------------------------------------------

from IMPORTS import *
from tts import speak_text, speak_async

# Fallback speak function with error handling
def speak(text: str, async_mode: bool = True) -> None:
    """
    Speak text using TTS. Automatically handles async/sync and errors.
    
    Args:
        text: Text to speak
        async_mode: If True, speak asynchronously (non-blocking). Default: True
    """
    try:
        if async_mode:
            future = speak_async(text)
            # Fire and forget (don't wait for completion)
            return
        else:
            speak_text(text)
    except Exception as e:
        print(f"[TTS ERROR] Failed to speak '{text[:50]}...': {e}")


def logic(speech):
    """
    Main logic handler for voice commands.
    Processes speech input and routes to appropriate handlers.
    """
    if speech.lower().startswith("jarvis") or speech.lower().endswith("jarvis"):
        speech = speech[6:].strip()
        print("Updated Speech:", speech)

        try:
            # Submit parallel classification tasks
            response_img_or_text = concurrent.futures.ThreadPoolExecutor().submit(
                deepInfra_TEXT.generate, 
                [{"role": "user", "content": "Text to Classify -->" + speech}], 
                system_prompt=BISECTORS.image_classification_prompt  # Fixed: was truncated [...] 
            )
            
            response_classifier = concurrent.futures.ThreadPoolExecutor().submit(
                deepInfra_TEXT.generate, 
                [{"role": "user", "content": "Text to Classify -->" + speech}], 
                system_prompt=BISECTORS.completion_classification_prompt  # Fixed: was truncated [...]
            )
            
            default_response = concurrent.futures.ThreadPoolExecutor().submit(
                deepInfra_TEXT.generate, 
                history_manager.history, 
                system_prompt=INSTRUCTIONS.human_response_v3_AVA, 
                stream=False
            )
            
            # Wait for all tasks to complete
            concurrent.futures.wait([response_img_or_text, response_classifier, default_response])
            
            print("Response Classifier >> ", "\033[91m" + response_classifier.result() + "\033[0m")
            print("Image or Text Classifier >> ", "\033[91m" + response_img_or_text.result() + "\033[0m")

            # Image/Content Generation Branch
            if "yes" in response_img_or_text.result().lower():
                speak("Sure Sir, Generating Your Image", async_mode=False)  # Wait for audio before proceeding
                decohere_ai.generate(speech)
                return
            
            # Confused Classification - Use Default Response
            elif all(x in response_classifier.result().lower() for x in ("vision", "website", "call", "youtube")):
                print("\033[91mConfused with Classification. Using Default Response\033[0m")
                speak(default_response.result())
                return

            # System Control Branch (Dark/Light Mode, Taskbar, etc.)
            elif "system control" in response_classifier.result().lower():
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    # Submit speak asynchronously and proceed immediately
                    speak_future = executor.submit(speak, "Sure Sir. Setting the Required Settings", False)

                    speech_lower = speech.lower()
                    
                    # Theme Control
                    if "dark" in speech_lower or "light" in speech_lower:
                        theme = 0 if "dark" in speech_lower else 1
                        system_theme.WindowsThemeManager().set_theme(theme)
                    
                    # Taskbar Alignment
                    elif any(alignment in speech_lower for alignment in ["left", "center", "centre", "right"]):
                        alignment = 0 if "left" in speech_lower else 1
                        taskbar.TaskbarCustomizer().set_alignment(alignment)
                    
                    # Temperature Display
                    elif "temperature" in speech_lower:
                        taskbar.TaskbarCustomizer().set_temperature_display(1)

                    # Wait for speech to finish
                    try:
                        speak_future.result(timeout=5)
                    except concurrent.futures.TimeoutError:
                        print("[WARN] Speak timeout - continuing anyway")

            # Vision/Camera Analysis Branch
            elif "vision" in response_classifier.result().lower():
                speak("Analysing, Please Wait", async_mode=False)  # Fixed: was speak("...") passed to submit directly
                image_path = camera_vision.realtime_vision()
                response_vison = deepInfra_VISION.generate(
                    speech, 
                    system_prompt=INSTRUCTIONS.vison_realtime_v1, 
                    image_path=image_path
                )
                print("AI>>", response_vison)
                os.remove(image_path)
                speak(response_vison)

            # Website Content Reading Branch (commented out - add back if needed)
            # elif "call" in response_classifier.result().lower():
            #     speak("Sure Sir. Calling")
            #     make_call.call()

            # Website Analysis Branch
            elif "website" in response_classifier.result().lower():
                site_markdown = jenna_reader.fetch_website_content(chrome_latest_url.get_latest_chrome_url())
                response = openrouter.generate(
                    f"METEDATA: {site_markdown}\n\nQUERY: {speech}", 
                    system_prompt="Keep you responses very short and concise"
                )
                speak(response)

            # Default Response Branch
            else: 
                print("AI>>", default_response.result())
                speak(default_response.result())

        except Exception as e:
            print(f"[ERROR] Logic error during speech processing: {e}")
            speak(f"Sorry sir, I encountered an error: {str(e)[:100]}")

    else:
        # Regular conversation (not a command)
        try:
            history_manager.store_history(history_manager.history + [{"role": "user", "content": speech}])
            print("\033[93mHuman >> {}\033[0m".format(speech))

            # Generate response
            chat_response = Hugging_Face_TEXT.generate(speech)
            print("\n\033[92mJARVIS >> {}\033[0m\n".format(chat_response))
            
            history_manager.update_file(speech, chat_response)
            speak(chat_response)
            
        except Exception as e:
            print(f"[ERROR] Conversation error: {e}")
            speak("Sorry, I couldn't process that. Please try again.")
