# PawPal+ Project Reflection

## 1. System Design

**a. Initial design**

- Briefly describe your initial UML design.
    - My design build s schedule which is a daily plan from Task objects and returns entries for UI or persistence. From the task it reads the owner and pets in which the owner owns any amount of pets. The owner creates task by assigning owner.id to task.owner_id

    Important to include: Sort tasks by priority (high → medium → low) and by longer duration first within the same priority.

- What classes did you include, and what responsibilities did you assign to each?
    - Owner - Should hold a list of their pets and their own scheduler so the app can schedule multiple people. Collect basic information from the Owner. Let the Owner be able to CURD their list of pets as well as tasks on their scheduler. 
    Pet - Should include the basic info for the pet.
    Scheduler - Creates the plan by collecting the information from the other components 
    Task - Creates a time block of the  routine of the owner/pet -- feedings, walks, medications, and appointments 
**b. Design changes**

- Did your design change during implementation?
- If yes, describe at least one change and why you made it.
    - I fixed the priority handlings, add the a create task method for the owner, enfore owener/pet consistency, honor owner's availabilty end, and execute rule hooks during scheduling.

Three core actions:
- Create a profile for the user and their pets (CURD Operations for pets) 
- Display today's tasks in order of priority and explain why 
- Allow the pet to have routines: going for a walk, getting cleaned, etc. 

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?
- How did you decide which constraints mattered most?

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.
- Why is that tradeoff reasonable for this scenario?

---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
- What kinds of prompts or questions were most helpful?

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.
- How did you evaluate or verify what the AI suggested?

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?
- Why were these tests important?

**b. Confidence**

- How confident are you that your scheduler works correctly?
- What edge cases would you test next if you had more time?

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?
