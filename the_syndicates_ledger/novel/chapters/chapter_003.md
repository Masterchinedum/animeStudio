# Chapter 3: Decryption Keys

The rain in the Edge-Water district did not fall so much as it drifted, a heavy, grease-slicked mist that clung to the reinforced glass of Ren’s twelfth-story apartment. Below, the neon signs of transit hubs and noodle stalls bled into the wet asphalt, painting the street level in fractured streaks of amber and electric blue. 

Ren stood by the narrow window, his fingers tracing the cool, metallic edge of the micro-drive Mei-Ling Vance had slipped into his pocket. It was a custom piece of hardware—brushed titanium wrapped in a carbon-fiber weave, heavy enough to feel like a bullet when held in the palm. It smelled faintly of her perfume, a dry, expensive scent of sandalwood and white tea that felt entirely foreign in this cramped, functional space.

Behind him, the low, rhythmic hum of cooling fans filled the room. 

Yuki Tanaka sat hunched over the secondary terminal, her knees pulled up to her chest on the mismatched swivel chair. She wore an oversized, faded black corporate-issue tech jacket with the sleeves pushed up to her elbows. Her fingers, smudged with gray graphite from a manual drafting pencil she still insisted on using, danced across a mechanical split keyboard.

"The architecture on this thing is beautiful," Yuki murmured, not looking up. Her eyes reflected the pale blue light of the terminal screen. "It’s not standard corporate issue, Ren. The encryption layers aren't using the syndicate's proprietary algorithms. It’s custom, multi-threaded. Whoever put this together didn't want the Ledger Custodians or the regional directors sniffing it."

"Can you bypass the handshake protocol?" Ren asked, his voice quiet. He didn't turn from the window. "We don't have the luxury of a brute-force attack. If the drive detects an unauthorized attempt, it might trigger a thermal wipe."

Yuki paused, her fingers hovering. She looked back at him, her dark eyes wide with a mixture of fatigue and sharp, ambitious curiosity. "I’ve already isolated the drive’s power loop on your secondary server. It’s completely air-gapped from the main Vesper City grid. Even if it tries to ping home, the signal will hit my dummy node and die. But Ren... where did you get this?"

Ren turned slowly, leaning his lower back against the window sill. He kept his hands in his pockets. "A contact at the gala. Someone who wants to know if Director Han’s death was as simple as the official report claims."

"A contact," Yuki repeated, her tone dry. She turned back to the screen. "You mean someone who has access to high-society encryption keys. This is Tier-6 level security, Ren. If Marcus Vance’s sweepers find out we’re hosting this kind of data, my Tier-3 clearance won't protect me. They’ll demote me to a zero before I can even pack my desk."

"Which is why we’re doing this here, off the books, on my equipment," Ren said. He walked over to stand behind her, his eyes scanning the cascading lines of green code. "I’m the one taking the risk, Yuki. If anything goes sideways, you were never here. You were auditing the logistics accounts for the cargo docks."

"We’re a team, Ren. You don't have to keep playing the martyr," she said, though her voice lacked conviction. She tapped a final sequence on the keyboard. "Initiating the decryption cascade. Hold your breath."

The hum of the secondary server deepened, shifting from a steady purr to a strained, high-pitched whine. On the screen, the concentric rings of the security firewall began to untangle, turning from red to amber, and finally to a solid, stable blue.

Ren leaned in closer, his hand resting on the back of Yuki’s chair. He could feel the tension in her shoulders, the slight tremor of her breath. 

A single directory file opened. It was remarkably clean, devoid of the usual corporate clutter or nested subfolders. There were only two primary items: a cryptographic log and a document titled *Active_Liabilities.dat*.

"Open the liabilities file," Ren instructed.

Yuki clicked the file. A spreadsheet populated the screen, but it wasn't financial data. It was a list of names, ranks, and corresponding Ledger profiles.

Ren’s eyes narrowed as he read the names. 

*Director Han – Tier 6 (Deceased)*  
*Vice-President Choi – Tier 5 (Active)*  
*Director Sterling – Tier 7 (Active)*  
*Director Vance – Tier 6 (Active)*  

Beside each name was a timestamped entry detailing specific, highly sensitive collateral. For Director Han, it was the offshore routing numbers for a series of shell companies used to bypass the syndicate's import taxes. For Vice-President Choi, it was a series of encrypted audio files labeled *Vesper_South_Transit_Bribes*. 

"My god," Yuki whispered, her hand flying to her mouth. "These aren't just files. These are the actual collateral deposits stored in the Ledger's encrypted vaults. Someone has been pulling them out."

"Not pulling them out," Ren corrected, his mind working with cold, mechanical precision. "They’re copying them. Look at the metadata. The files were accessed using a localized physical terminal. But look at the broker ID at the bottom of the ledger."

Yuki zoomed in on the bottom-right corner of the screen. A single, recurring cryptographic signature was stamped on every transaction: *The_Tailor*.

"The Tailor," Yuki read aloud. "Who is that? A broker? A custodian?"

"A ghost," Ren said. He felt a sudden, sharp chill in his chest. "A blackmailer who understands the Ledger's internal structure well enough to navigate the vaults without triggering an automatic demotion loop. They’re holding these secrets, waiting for the right moment to release them. Han was just the first."

"Look at the next target," Yuki said, her voice shaking as she pointed to the screen. "Vice-President Choi. His entry has a countdown timer. It’s set for forty-eight hours from now. If this is real, his collateral—the transit bribes—will be published to the public Ledger. He’ll drop to Tier 1 instantly."

Ren stared at Choi’s name. This was the predictive advantage he needed. If he could anticipate the next leak, he could intercept the broker, trace the terminal, and perhaps find the leverage he needed to protect himself and his brother, Kenji. But the cost of this knowledge was high. Very high.

"Yuki," Ren said, his voice dropping to a low, warning register. "You shouldn't have seen this. This is classified at the highest level of the executive tier. If Chairman Kang’s security team realizes you have this data, they won't just demote you. They’ll erase you."

Yuki looked up at him, her face pale in the blue glow of the terminal. "I wanted to help you, Ren. I wanted to prove I could handle the audit. But this... this is treason against the syndicate. If Marcus Vance—"

"Marcus Vance won't find out," Ren said, placing a reassuring hand on her shoulder. "But we need to close the file now. Copy the target list to a secure, localized drive and wipe the server's cache."

"I'm on it," Yuki said, her fingers flying across the keys. "Copying the target list... eighty percent... ninety..."

Suddenly, the screen flickered. The steady blue light shifted to a harsh, strobing yellow. 

A diagnostic alert flashed in the center of the screen: *INTRUSIVE HANDSHAKE DETECTED. LOCALIZED PACKET SWEEP IN PROGRESS.*

Ren’s posture stiffened. "What is that? I thought you said the server was air-gapped."

"It is!" Yuki’s voice rose in panic. Her fingers scrambled over the keyboard, but the system was unresponsive. "The drive... the micro-drive itself had a passive, low-frequency transponder built into the casing. It didn't need our network to ping out. It used the local cellular tower to broadcast its physical location the moment the primary encryption key was decrypted."

"Who is sweeping?" Ren demanded.

"The signature is... Oh no. It’s Kang Global Private Security. Marcus’s division," Yuki whimpered, her eyes darting around the room as if the walls were closing in. "They’re running a silent, localized sweep of this entire block. They’re tracking the transponder's signal. They’ll be here in minutes."

Ren didn't hesitate. He reached across Yuki, pushing her out of the chair. 

"Get your things," he ordered.

"Ren, the data—"

"Get your things and get out of here through the service elevator. Now!"

Ren grabbed the titanium micro-drive from the interface slot, but the yellow alert on the screen was already transitioning to a solid, bloody red: *TRACE COMPLETE. TARGET ACQUIRED.*

The sweep was too fast. If they left now, the data on the secondary server’s hard drives would be captured intact, linking his apartment, his biometric signature, and Yuki's terminal to the decrypted files. 

Ren reached into his desk drawer and pulled out a heavy, high-density ceramic spike tool—a manual hard-drive destroyer designed for emergency field audits. 

"Ren, what are you doing?" Yuki cried, her jacket clutched to her chest as she stood by the door.

"Go, Yuki!" Ren shouted over the rising whine of the server's cooling fans, which were now screaming at maximum capacity as the remote sweep attempted to force a system override.

With a grunt of effort, Ren slammed the ceramic spike directly into the center of the secondary server's aluminum housing. The metal buckled with a sharp, metallic crunch. He pulled the spike back and drove it down again, shattering the primary solid-state drives into fractured shards of silicon and plastic. 

A bright spark erupted from the power supply, filling the small room with the sharp, acrid smell of ozone and burning copper. The screen flickered once, twice, and then went completely dark.

Ren stood in the smoking ruins of his workspace, his chest heaving, the heavy ceramic tool still dripping with grey thermal paste. 

Through the thin walls of his apartment, he heard the distant, rhythmic thud of heavy boots ascending the concrete stairwell of the building. Marcus Vance’s sweepers were already in the lobby.

He looked toward the doorway, but Yuki was already gone, her soft footsteps fading down the service corridor. 

Ren pocketed the physical micro-drive, grabbed a bottle of industrial solvent from under the sink, and poured it over the ruined server chassis, igniting the plastic with a single spark from his lighter. As the small, controlled fire began to consume the remaining evidence, he stepped out into the rain-slicked night, leaving his home behind.
